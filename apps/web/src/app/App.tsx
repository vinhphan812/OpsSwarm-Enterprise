import { Route, Routes } from "react-router";
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
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </div>
    </Providers>
  );
}
