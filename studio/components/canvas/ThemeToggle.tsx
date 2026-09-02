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
    // The root layout's own blocking <head> script already applies
    // data-theme="light" before first paint (avoiding a flash), so this
    // isn't fixing a visible bug today -- but syncing here too means this
    // component's own correctness doesn't quietly depend on that separate
    // script existing.
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light") {
      setTheme("light");
      applyTheme("light");
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
