from fastapi import Query


class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=200),
        search: str | None = Query(None, min_length=1, max_length=200),
        sort_by: str = Query("created_at", max_length=50),
        sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    ):
        self.page = page
        self.limit = limit
        self.skip = (page - 1) * limit
        self.search = search.strip() if search else None
        self.sort_by = sort_by
        self.sort_order = sort_order

    def sort(self, allowed: set[str], default: str = "created_at") -> tuple[str, int]:
        field = self.sort_by if self.sort_by in allowed else default
        return field, 1 if self.sort_order == "asc" else -1


def page_result(items: list, total: int, params: PaginationParams) -> dict:
    return {
        "items": items,
        "page": params.page,
        "limit": params.limit,
        "total": total,
        "has_next": params.skip + len(items) < total,
    }
