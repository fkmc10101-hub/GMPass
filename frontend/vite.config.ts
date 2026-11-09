import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중에는 /api 요청을 FastAPI(8000)로 넘긴다
// GitHub Pages(https://<아이디>.github.io/GMPass/)에 올릴 때는 VITE_BASE=/GMPass/ 로 빌드한다
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: { "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: true } },
  },
});
