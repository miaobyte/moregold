import { forwardRef, type InputHTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        'h-7 rounded border border-[#3a3e4a] bg-[#2a2e39] px-1.5 text-xs text-fg',
        'file:border-0 file:bg-transparent file:text-sm file:font-medium',
        'placeholder:text-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#1976d2]',
        '[color-scheme:dark]',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

export { Input };
