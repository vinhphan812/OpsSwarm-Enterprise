import { Route, Routes } from "react-router";
import { DEMO_PATH, LIVE_PATH } from "@/core/twin/demoMode";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { Providers } from "./Providers";
import { TwinPage } from "@/pages/TwinPage";
import "./App.css";

export function App() {
  return (
    <Providers>
      <div className="app">
        <Routes>
          <Route path="/" element={<TwinPage />} />
          <Route path={DEMO_PATH} element={<TwinPage />} />
          <Route path={LIVE_PATH} element={<TwinPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </div>
    </Providers>
  );
}
