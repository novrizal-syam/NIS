import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

/** Signature pad (pointer/touch). Keyboard users can type their name instead; it is drawn as a
 * script signature. Reports a PNG data URL, or null while empty. */
export function SignaturePad({ onChange }: { onChange: (png: string | null) => void }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [typed, setTyped] = useState('');
  const [dirty, setDirty] = useState(false);

  const ctx = () => ref.current?.getContext('2d') ?? null;
  const clear = () => {
    const c = ref.current;
    const g = ctx();
    if (c && g) {
      g.fillStyle = '#ffffff';
      g.fillRect(0, 0, c.width, c.height);
    }
    setDirty(false);
    onChange(null);
  };
  useEffect(clear, []); // eslint-disable-line react-hooks/exhaustive-deps

  const pos = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [
      ((e.clientX - r.left) * e.currentTarget.width) / r.width,
      ((e.clientY - r.top) * e.currentTarget.height) / r.height,
    ] as const;
  };
  const done = () => {
    drawing.current = false;
    if (ref.current) onChange(ref.current.toDataURL('image/png'));
  };
  const typeName = (name: string) => {
    setTyped(name);
    const c = ref.current;
    const g = ctx();
    if (!c || !g) return;
    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, c.width, c.height);
    if (!name.trim()) {
      setDirty(false);
      onChange(null);
      return;
    }
    g.fillStyle = '#1a1a1a';
    g.font = 'italic 40px "Brush Script MT", cursive';
    g.fillText(name, 16, c.height / 2 + 14);
    setDirty(true);
    onChange(c.toDataURL('image/png'));
  };

  return (
    <div className="flex flex-col gap-2">
      <canvas
        ref={ref}
        width={600}
        height={180}
        role="img"
        aria-label={t('billing.signatureArea')}
        className="w-full max-w-xl touch-none rounded-control border border-border-strong bg-white"
        onPointerDown={(e) => {
          const g = ctx();
          if (!g) return;
          drawing.current = true;
          e.currentTarget.setPointerCapture(e.pointerId);
          const [x, y] = pos(e);
          g.strokeStyle = '#1a1a1a';
          g.lineWidth = 3;
          g.lineCap = 'round';
          g.beginPath();
          g.moveTo(x, y);
        }}
        onPointerMove={(e) => {
          if (!drawing.current) return;
          const g = ctx();
          const [x, y] = pos(e);
          g?.lineTo(x, y);
          g?.stroke();
          setDirty(true);
        }}
        onPointerUp={done}
        onPointerLeave={() => drawing.current && done()}
      />
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('billing.typeSignature')} className="min-w-0 flex-1">
          <Input value={typed} onChange={(e) => typeName(e.target.value)} />
        </Field>
        <Button
          variant="secondary"
          disabled={!dirty}
          onClick={() => {
            setTyped('');
            clear();
          }}
        >
          {t('billing.clearSignature')}
        </Button>
      </div>
    </div>
  );
}
