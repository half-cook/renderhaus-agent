"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

const STORAGE_KEY = "renderhaus.studio.theme";

function applyTheme(theme: "light" | "dark") {
  if (theme === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light") {
      setTheme("light");
    }
  }, []);

  return (
    <button
      className="icon-btn"
      type="button"
      aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
      onClick={() => {
        const next = theme === "light" ? "dark" : "light";
        setTheme(next);
        applyTheme(next);
        localStorage.setItem(STORAGE_KEY, next);
      }}
    >
      {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}
