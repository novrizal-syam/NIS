import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import id from './locales/id.json';

export const LANGUAGES = ['id', 'en'] as const;
export type Language = (typeof LANGUAGES)[number];
const STORAGE_KEY = 'nustrad.lang';

function savedLanguage(): Language {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'id' || v === 'en') return v;
  } catch {
    /* storage unavailable */
  }
  return 'id';
}

void i18n.use(initReactI18next).init({
  resources: { id: { translation: id }, en: { translation: en } },
  lng: savedLanguage(),
  fallbackLng: 'id',
  interpolation: { escapeValue: false },
});

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng;
  try {
    localStorage.setItem(STORAGE_KEY, lng);
  } catch {
    /* storage unavailable */
  }
});

export default i18n;
