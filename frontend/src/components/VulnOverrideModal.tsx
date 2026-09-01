import { useEffect, useRef, useState } from "react";
import type { AggregatedVulnerability } from "../utils/health";

interface Props {
  open: boolean;
  row: AggregatedVulnerability | null;
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (fixedVersion: string, remark: string) => void;
  onRevert: () => void;
}

export default function VulnOverrideModal({
  open,
  row,
  saving,
  error,
  onClose,
  onSave,
  onRevert,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [fixedVersion, setFixedVersion] = useState("");
  const [remark, setRemark] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      setFixedVersion(row?.fixed_versions ?? "");
      setRemark(row?.remark ?? "");
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [open, row]);

  if (!row) return null;

  return (
    <dialog ref={dialogRef} className="modal" onClose={onClose}>
      <form
        className="modal__panel"
        onSubmit={(e) => {
          e.preventDefault();
          onSave(fixedVersion, remark);
        }}
      >
        <div className="modal__header">
          <h3 className="modal__title">취약점 수정</h3>
          <button
            type="button"
            className="modal__close"
            aria-label="닫기"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="modal__body">
          <div className="modal__field">
            <span className="modal__label">문제 코드</span>
            <div className="modal__readonly">{row.problem_code || "—"}</div>
          </div>
          <div className="modal__field">
            <span className="modal__label">패키지명</span>
            <div className="modal__readonly">{row.artifact}</div>
          </div>
          <div className="modal__field">
            <span className="modal__label">취약 버전</span>
            <div className="modal__readonly">{row.versions || "—"}</div>
          </div>
          <label className="modal__field">
            <span className="modal__label">해결 버전</span>
            <input
              type="text"
              value={fixedVersion}
              onChange={(e) => setFixedVersion(e.target.value)}
              placeholder="비우면 미해결"
              disabled={saving}
            />
          </label>
          <label className="modal__field">
            <span className="modal__label">비고</span>
            <textarea
              rows={4}
              value={remark}
              onChange={(e) => setRemark(e.target.value)}
              disabled={saving}
            />
          </label>
          {error && <div className="modal__error">{error}</div>}
        </div>
        <div className="modal__footer">
          {row.has_override && (
            <button
              type="button"
              className="btn-secondary modal__revert"
              disabled={saving}
              onClick={onRevert}
            >
              되돌리기
            </button>
          )}
          <div className="modal__footer-spacer" />
          <button
            type="button"
            className="btn-secondary"
            disabled={saving}
            onClick={onClose}
          >
            취소
          </button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
