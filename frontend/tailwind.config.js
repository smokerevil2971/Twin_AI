/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        // App backgrounds
        'bg-app':     '#F9FAFB', // gray-50
        'bg-card':    '#FFFFFF', // white
        'bg-raised':  '#F3F4F6', // gray-100
        'bg-input':   '#F9FAFB', // gray-50
        // Borders
        border:       '#E5E7EB', // gray-200
        // Brand & Accents
        brand:        '#111827', // gray-900 (Black styling)
        'brand-hover':'#374151', // gray-700
        accent:       '#111827', // Use dark charcoal for primary buttons
        'accent-hover':'#374151',
        // Status
        success:      '#10B981', // emerald-500
        warning:      '#F59E0B', // amber-500
        danger:       '#EF4444', // red-500
        teal:         '#0EA5E9',
        // Text
        'text-primary':   '#111827', // gray-900
        'text-secondary': '#6B7280', // gray-500
        'text-muted':     '#9CA3AF', // gray-400
      },
      boxShadow: {
        card:   '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        raised: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        modal:  '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
        toast:  '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
      },
      borderRadius: {
        card: '16px', // larger rounded corners like linear/stripe
      },
      animation: {
        'shimmer': 'shimmer 1.5s infinite',
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-in': 'slideIn 0.25s ease-out',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        slideIn: {
          from: { transform: 'translateX(100%)' },
          to:   { transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
}
