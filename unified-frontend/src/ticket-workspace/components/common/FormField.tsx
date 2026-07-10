import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

interface FieldWrapperProps {
  label: string;
  hint?: string;
  children?: ReactNode;
}

function FieldWrapper({ label, hint, children }: FieldWrapperProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate-600">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-[11px] leading-relaxed text-muted">{hint}</span>}
    </label>
  );
}

const fieldBase =
  "w-full rounded-md2 border border-border bg-surface px-3.5 py-2.5 text-sm text-slate-900 " +
  "placeholder:text-muted/60 shadow-xs transition-all duration-150 " +
  "focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function TextInput({
  label,
  hint,
  ...rest
}: FieldWrapperProps & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <FieldWrapper label={label} hint={hint}>
      <input className={fieldBase} {...rest} />
    </FieldWrapper>
  );
}

export function TextArea({
  label,
  hint,
  ...rest
}: FieldWrapperProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <FieldWrapper label={label} hint={hint}>
      <textarea className={`${fieldBase} min-h-[96px] resize-y leading-relaxed`} {...rest} />
    </FieldWrapper>
  );
}

export function SelectInput({
  label,
  hint,
  children,
  ...rest
}: FieldWrapperProps & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <FieldWrapper label={label} hint={hint}>
      <select className={`${fieldBase} cursor-pointer`} {...rest}>
        {children}
      </select>
    </FieldWrapper>
  );
}
