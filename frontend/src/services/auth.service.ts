import api from "./api";

export const auditService = {
  async list(page = 1, page_size = 20) {
    const response = await api.get("/audit-logs", {
      params: {
        page,
        page_size,
      },
    });

    return response.data;
  },
};