import api from "./api";

export const userService = {
  async list(page = 1, page_size = 10) {
    const response = await api.get("/users", {
      params: {
        page,
        page_size,
      },
    });

    return response.data;
  },

  async get(id: string) {
    const response = await api.get(`/users/${id}`);
    return response.data;
  },
};