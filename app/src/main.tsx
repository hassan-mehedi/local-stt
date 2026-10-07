import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppProvider } from "./lib/app";
import Pill from "./pill/Pill";
import "./styles.css";

const isPill = location.hash.startsWith("#/pill");
if (isPill) document.documentElement.classList.add("pill-page");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {isPill ? <Pill /> : <AppProvider><App /></AppProvider>}
  </StrictMode>,
);
