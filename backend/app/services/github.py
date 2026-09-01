from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

from app.config import settings


class GitHubError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RepoFile:
    path: str
    content: str
    sha: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    html_url: str
    state: str
    merged: bool
    title: str
    node_id: str | None = None


def _headers() -> dict[str, str]:
    if not settings.github_token:
        raise GitHubError("GITHUB_TOKEN is not configured", status_code=503)
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.github_token}",
    }


def _api(path: str) -> str:
    return f"{settings.github_api_base.rstrip('/')}{path}"


def _graphql_url() -> str:
    base = settings.github_api_base.rstrip("/")
    if base.endswith("/api/v3"):
        return base[: -len("/api/v3")] + "/api/graphql"
    return f"{settings.github_base_url.rstrip('/')}/api/graphql"


async def get_file(owner: str, repo: str, path: str, *, ref: str) -> RepoFile | None:
    url = _api(f"/repos/{owner}/{repo}/contents/{path}")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={"ref": ref},
            headers=_headers(),
            timeout=30.0,
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitHubError(
                f"get_file failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        data = response.json()

    content = base64.b64decode(data["content"]).decode("utf-8")
    return RepoFile(path=path, content=content, sha=data["sha"])


async def list_paths_named(
    owner: str,
    repo: str,
    *,
    ref: str,
    filename: str,
) -> list[str]:
    """Return all blob paths whose basename equals filename (recursive tree)."""
    headers = _headers()
    async with httpx.AsyncClient() as client:
        branch_resp = await client.get(
            _api(f"/repos/{owner}/{repo}/branches/{ref}"),
            headers=headers,
            timeout=30.0,
        )
        if branch_resp.status_code == 404:
            return []
        if branch_resp.status_code >= 400:
            raise GitHubError(
                f"list_paths_named branch failed: {branch_resp.text[:300]}",
                status_code=branch_resp.status_code,
            )
        branch = branch_resp.json()
        try:
            tree_sha = branch["commit"]["commit"]["tree"]["sha"]
        except (KeyError, TypeError) as exc:
            raise GitHubError(
                f"list_paths_named: unexpected branch payload for {owner}/{repo}",
                status_code=502,
            ) from exc

        tree_resp = await client.get(
            _api(f"/repos/{owner}/{repo}/git/trees/{tree_sha}"),
            params={"recursive": "1"},
            headers=headers,
            timeout=60.0,
        )
        if tree_resp.status_code >= 400:
            raise GitHubError(
                f"list_paths_named tree failed: {tree_resp.text[:300]}",
                status_code=tree_resp.status_code,
            )
        tree = tree_resp.json()

    if not isinstance(tree, dict):
        return []
    if tree.get("truncated"):
        raise GitHubError(
            f"git tree truncated for {owner}/{repo}; cannot list all {filename}",
            status_code=502,
        )
    paths: list[str] = []
    target = filename.lower()
    for item in tree.get("tree") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "blob":
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        base = path.rsplit("/", 1)[-1]
        if base.lower() == target:
            paths.append(path)
    paths.sort(key=str.lower)
    return paths


async def get_ref_sha(owner: str, repo: str, ref: str) -> str:
    url = _api(f"/repos/{owner}/{repo}/git/ref/{ref}")
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers(), timeout=30.0)
        if response.status_code >= 400:
            raise GitHubError(
                f"get_ref failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        data = response.json()
    return str(data["object"]["sha"])


async def create_branch(owner: str, repo: str, *, branch: str, from_sha: str) -> None:
    url = _api(f"/repos/{owner}/{repo}/git/refs")
    payload = {"ref": f"refs/heads/{branch}", "sha": from_sha}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=_headers(), timeout=30.0)
        if response.status_code == 201:
            return
        if response.status_code == 422 and "already exists" in response.text.lower():
            return
        if response.status_code >= 400:
            raise GitHubError(
                f"create_branch failed: {response.text[:300]}",
                status_code=response.status_code,
            )


async def put_file(
    owner: str,
    repo: str,
    *,
    path: str,
    content: str,
    message: str,
    branch: str,
    sha: str | None,
) -> None:
    url = _api(f"/repos/{owner}/{repo}/contents/{path}")
    payload: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    async with httpx.AsyncClient() as client:
        response = await client.put(url, json=payload, headers=_headers(), timeout=30.0)
        if response.status_code >= 400:
            raise GitHubError(
                f"put_file failed: {response.text[:300]}",
                status_code=response.status_code,
            )


async def create_pull(
    owner: str,
    repo: str,
    *,
    title: str,
    body: str,
    head: str,
    base: str,
) -> PullRequest:
    url = _api(f"/repos/{owner}/{repo}/pulls")
    payload = {"title": title, "body": body, "head": head, "base": base}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=_headers(), timeout=30.0)
        if response.status_code >= 400:
            raise GitHubError(
                f"create_pull failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        data = response.json()
    return PullRequest(
        number=int(data["number"]),
        html_url=str(data["html_url"]),
        state=str(data["state"]),
        merged=bool(data.get("merged", False)),
        title=str(data.get("title", title)),
        node_id=data.get("node_id"),
    )


def _pull_from_data(data: dict, *, fallback_title: str = "") -> PullRequest:
    return PullRequest(
        number=int(data["number"]),
        html_url=str(data["html_url"]),
        state=str(data["state"]),
        merged=bool(data.get("merged", False)),
        title=str(data.get("title", fallback_title)),
        node_id=data.get("node_id"),
    )


async def get_pull(owner: str, repo: str, number: int) -> PullRequest:
    url = _api(f"/repos/{owner}/{repo}/pulls/{number}")
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers(), timeout=30.0)
        if response.status_code >= 400:
            raise GitHubError(
                f"get_pull failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        data = response.json()
    return _pull_from_data(data)


async def get_pull_raw(owner: str, repo: str, number: int) -> dict:
    url = _api(f"/repos/{owner}/{repo}/pulls/{number}")
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers(), timeout=30.0)
        if response.status_code >= 400:
            raise GitHubError(
                f"get_pull failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        return response.json()


async def enable_automerge(pull_node_id: str) -> tuple[bool, str]:
    """Enable GitHub auto-merge. Tries MERGE → SQUASH → REBASE."""
    last_error = "unknown error"
    for method in ("MERGE", "SQUASH", "REBASE"):
        query = """
        mutation($pullRequestId: ID!, $mergeMethod: PullRequestMergeMethod!) {
          enablePullRequestAutoMerge(input: {
            pullRequestId: $pullRequestId,
            mergeMethod: $mergeMethod
          }) {
            pullRequest { number autoMergeRequest { enabledAt } }
          }
        }
        """
        payload = {
            "query": query,
            "variables": {"pullRequestId": pull_node_id, "mergeMethod": method},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _graphql_url(),
                json=payload,
                headers=_headers(),
                timeout=30.0,
            )
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                continue
            data = response.json()
            errors = data.get("errors") or []
            if errors:
                last_error = str(errors[0].get("message") or errors[0])
                # Try next merge method when this one is not allowed
                continue
            if not data.get("data", {}).get("enablePullRequestAutoMerge"):
                last_error = "enablePullRequestAutoMerge returned empty"
                continue
            return True, method
    return False, last_error


async def is_org_owner(login: str) -> bool:
    """True if login is an active owner (role=admin) of GITHUB_ORG."""
    username = login.strip()
    if not username or not settings.github_token:
        return False
    org = settings.github_org.strip()
    if not org:
        return False
    url = _api(f"/orgs/{org}/memberships/{username}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=_headers(), timeout=15.0)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        data = response.json()
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    role = str(data.get("role") or "").lower()
    state = str(data.get("state") or "").lower()
    return role == "admin" and state == "active"


async def list_all_organizations() -> list[str]:
    """Return all org logins visible to GITHUB_TOKEN (paginated)."""
    headers = _headers()
    names: list[str] = []
    since = 0
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                _api("/organizations"),
                params={"per_page": 100, "since": since},
                headers=headers,
                timeout=60.0,
            )
            if response.status_code >= 400:
                raise GitHubError(
                    f"list organizations failed: {response.text[:300]}",
                    status_code=response.status_code,
                )
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict) and item.get("login"):
                    names.append(str(item["login"]))
                oid = item.get("id") if isinstance(item, dict) else None
                if isinstance(oid, int):
                    since = max(since, oid)
            if len(batch) < 100:
                break
    return names


async def list_org_repos(org: str) -> list[str]:
    """Return repository names for an organization (paginated)."""
    headers = _headers()
    names: list[str] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                _api(f"/orgs/{org}/repos"),
                params={"per_page": 100, "page": page, "type": "all"},
                headers=headers,
                timeout=60.0,
            )
            if response.status_code >= 400:
                raise GitHubError(
                    f"list repos for {org} failed: {response.text[:300]}",
                    status_code=response.status_code,
                )
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
            if len(batch) < 100:
                break
            page += 1
    return names


async def merge_pull(
    owner: str,
    repo: str,
    number: int,
    *,
    merge_method: str = "merge",
) -> tuple[bool, str]:
    """Merge PR via REST. Returns (ok, detail). Only succeeds when GitHub allows merge."""
    url = _api(f"/repos/{owner}/{repo}/pulls/{number}/merge")
    last_error = "merge failed"
    for method in (merge_method, "merge", "squash", "rebase"):
        payload = {"merge_method": method}
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url, json=payload, headers=_headers(), timeout=30.0
            )
            if response.status_code in (200, 201):
                return True, method
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code == 405:
                # Method not allowed — try next
                continue
            if response.status_code == 409:
                # Conflict / not mergeable yet
                return False, last_error
    return False, last_error


async def merge_if_ready(owner: str, repo: str, number: int) -> PullRequest:
    """If PR is open and mergeable_state is clean, merge it (CI already green)."""
    data = await get_pull_raw(owner, repo, number)
    pr = _pull_from_data(data)
    if pr.merged or pr.state != "open":
        return pr
    if not settings.transfer_auto_merge:
        return pr

    mergeable = data.get("mergeable")
    mergeable_state = str(data.get("mergeable_state") or "")
    # clean / has_hooks = ready; blocked often means reviews still required
    if mergeable is True and mergeable_state in ("clean", "has_hooks"):
        ok, _ = await merge_pull(owner, repo, number)
        if ok:
            return await get_pull(owner, repo, number)
    return pr
