import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';
const STORAGE_KEY = 'nustrad.theme';

interface ThemeContextValue {
  theme: ThemeChoice;
  setTheme: (t: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readSaved(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark') return v;
  } catch {
    /* storage unavailable */
  }
  return 'system';
}

/** Applies the choice as <html data-theme>. "system" removes the attribute so CSS follows the OS. */
export function applyTheme(theme: ThemeChoice) {
  const root = document.documentElement;
  if (theme === 'system') delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readSaved);

  useEffect(() => applyTheme(theme), [theme]);

  const setTheme = useCallback((t: ThemeChoice) => {
    setThemeState(t);
    try {
      if (t === 'system') localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* storage unavailable */
    }
  }, []);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
}
