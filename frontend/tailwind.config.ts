import type { Config } from 'tailwindcss';

// Every colour points at a CSS variable from src/theme/tokens.css, so light and
// dark themes come from the same class names. Variables hold "R G B" triplets
// so Tailwind opacity modifiers (bg-brand-gold/20) keep working.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    screens: {
      sm: '640px',
      md: '768px',
      lg: '1024px',
      xl: '1280px',
    },
    extend: {
      colors: {
        brand: {
          gold: token('brand-gold'),
          ink: token('brand-ink'),
          mist: token('brand-mist'),
        },
        surface: {
          DEFAULT: token('surface'),
          muted: token('surface-muted'),
          raised: token('surface-raised'),
          inverse: token('surface-inverse'),
        },
        fg: {
          DEFAULT: token('text'),
          body: token('text-body'),
          secondary: token('text-secondary'),
          muted: token('text-muted'),
          accent: token('text-accent'),
          'on-inverse': token('text-on-inverse'),
        },
        'on-gold': {
          DEFAULT: token('on-gold'),
          muted: token('on-gold-muted'),
        },
        border: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        focus: token('focus-ring'),
        success: { DEFAULT: token('success'), tint: token('success-tint') },
        warning: { DEFAULT: token('warning'), tint: token('warning-tint') },
        danger: { DEFAULT: token('danger'), tint: token('danger-tint') },
        info: { DEFAULT: token('info'), tint: token('info-tint') },
        sidebar: {
          DEFAULT: token('brand-ink'),
          fg: token('sidebar-fg'),
          muted: token('sidebar-muted'),
          hover: token('sidebar-hover'),
        },
      },
      fontFamily: {
        heading: ['Prompt', 'system-ui', 'sans-serif'],
        sans: ['Montserrat', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        'page-title': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'section-title': ['18px', { lineHeight: '26px', fontWeight: '600' }],
        'card-title': ['15px', { lineHeight: '22px', fontWeight: '600' }],
        body: ['14px', { lineHeight: '22px' }],
        table: ['13px', { lineHeight: '20px' }],
        small: ['12px', { lineHeight: '18px' }],
        caption: ['11px', { lineHeight: '16px', fontWeight: '500' }],
        eyebrow: ['11px', { lineHeight: '16px', fontWeight: '700', letterSpacing: '0.18em' }],
      },
      borderRadius: {
        card: '8px',
        control: '6px',
        pill: '999px',
      },
      width: {
        sidebar: '248px',
      },
    },
  },
  plugins: [],
};

export default config;
