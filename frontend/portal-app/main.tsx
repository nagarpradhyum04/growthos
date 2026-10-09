import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { auth } from "../src/api";
import Portal from "../src/portal/Portal";
import PortalLogin from "../src/portal/PortalLogin";
import "../src/styles.css";

function RequireCustomer() {
  return auth.token && auth.role === "customer" ? <Portal /> : <Navigate to="/login" replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<PortalLogin />} />
        <Route path="/portal/*" element={<RequireCustomer />} />
        <Route path="*" element={<Navigate to="/portal" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
