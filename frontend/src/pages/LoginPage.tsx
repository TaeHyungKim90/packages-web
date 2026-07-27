import { useSearchParams } from "react-router-dom";
import { getLoginUrl } from "../api/client";

export default function LoginPage() {
  const [params] = useSearchParams();
  const error = params.get("error");

  return (
    <div className="login">
      <div className="login__panel">
        <h2 className="login__title">로그인</h2>
        <p className="login__desc">
          GitHub Enterprise(SK) 계정으로 로그인하세요.
        </p>
        {error && <div className="login__error">{error}</div>}
        <a className="btn-primary login__btn" href={getLoginUrl()}>
          GitHub(SK)로 로그인
        </a>
      </div>
    </div>
  );
}
