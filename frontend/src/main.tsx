import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Typefaces: bundled with the app (SIL Open Font License), latin subset, no network fetch.
import "@fontsource-variable/fraunces/opsz.css";
import "@fontsource-variable/fraunces/opsz-italic.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-400-italic.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";

import App from "./App";
import "./styles.css";
import "./theme.css";
import "./styles/tokens.css";
import "./styles/materials.css";
import "./styles/layout.css";
import "./styles/typography.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
