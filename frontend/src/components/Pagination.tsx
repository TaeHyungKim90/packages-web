import { pageWindow } from "../utils/result";

interface Props {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({
  currentPage,
  totalPages,
  totalItems,
  pageSize,
  onPageChange,
}: Props) {
  if (totalItems <= pageSize) return null;

  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalItems);
  const pages = pageWindow(currentPage, totalPages);

  return (
    <nav className="pagination" aria-label="페이지">
      <button
        type="button"
        className="pagination__btn"
        disabled={currentPage <= 1}
        onClick={() => onPageChange(1)}
      >
        처음
      </button>
      <button
        type="button"
        className="pagination__btn"
        disabled={currentPage <= 1}
        onClick={() => onPageChange(currentPage - 1)}
      >
        이전
      </button>
      {pages.map((item, idx) =>
        item === "ellipsis" ? (
          <span key={`e-${idx}`} className="pagination__ellipsis">
            …
          </span>
        ) : (
          <button
            key={item}
            type="button"
            className={`pagination__btn pagination__num${item === currentPage ? " pagination__num--active" : ""}`}
            aria-current={item === currentPage ? "page" : undefined}
            onClick={() => onPageChange(item)}
          >
            {item}
          </button>
        ),
      )}
      <button
        type="button"
        className="pagination__btn"
        disabled={currentPage >= totalPages}
        onClick={() => onPageChange(currentPage + 1)}
      >
        다음
      </button>
      <button
        type="button"
        className="pagination__btn"
        disabled={currentPage >= totalPages}
        onClick={() => onPageChange(totalPages)}
      >
        끝
      </button>
      <span className="pagination__info">
        {start}–{end} / {totalItems}건
      </span>
    </nav>
  );
}
