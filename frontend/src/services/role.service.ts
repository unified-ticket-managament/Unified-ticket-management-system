import api from "./api";

export const roleService = {
  async list(page = 1, page_size = 10) {
    const response = await api.get("/roles", {
      params: {
        page,
        page_size,
      },
    });

    return response.data;
  },

  async get(id: string) {
    const response = await api.get(`/roles/${id}`);
    return response.data;
  },
};