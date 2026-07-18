import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import "./styles/tokens.css";
import "./styles/global.css";

import { App } from "./App";
import { Library } from "./routes/Library";
import { Reader } from "./routes/Reader";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Library /> },
      { path: "read/:bookId", element: <Reader /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
