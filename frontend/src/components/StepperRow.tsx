interface StepperRowProps {
  label: string;
  hint?: string;
  value: number;
  unit: string;
  /** 0 = inactive/grey, > 0 = active/orange */
  active: boolean;
  min?: number;
  onStep: (direction: -1 | 1) => void;
}

export function stepSize(unit: string): number {
  return unit === "pcs" ? 1 : 0.1;
}

export function formatValue(value: number, unit: string): string {
  if (unit === "pcs") return `${Math.round(value)}`;
  return `${Math.round(value * 100) / 100}`;
}

export default function StepperRow({ label, hint, value, unit, active, min = 0, onStep }: StepperRowProps) {
  return (
    <div className={active ? "stepper-row active" : "stepper-row"}>
      <div className="stepper-label">
        <span>{label}</span>
        {hint && <span className="stepper-hint">{hint}</span>}
      </div>
      <div className="stepper-controls">
        <button
          aria-label={`Decrease ${label}`}
          disabled={value <= min}
          onClick={() => onStep(-1)}
        >
          −
        </button>
        <span className="stepper-value">{formatValue(value, unit)}</span>
        <button aria-label={`Increase ${label}`} onClick={() => onStep(1)}>
          +
        </button>
      </div>
      <span className="stepper-unit">{unit}</span>
    </div>
  );
}
