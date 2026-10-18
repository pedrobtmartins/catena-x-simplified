// The colour theme: the system's by default, or light or dark as the user picks it. The choice is
// kept in this browser; index.html applies it before the first paint, so a reload does not flash.
import { useState } from "react";

export type Theme = "system" | "light" | "dark";

const KEY = "cxs-theme";

export function storedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system"; // storage blocked: follow the system
  }
}

function apply(theme: Theme) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // not kept across reloads; the page still switches
  }
}

const OPTIONS: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  return (
    <div className="chip-group theme-switch" role="group" aria-label="Colour theme">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className="chip"
          aria-pressed={theme === option.value}
          title={option.value === "system" ? "Follow the system's light or dark setting" : undefined}
          onClick={() => {
            apply(option.value);
            setTheme(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
