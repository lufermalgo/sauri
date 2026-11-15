export type TimeChipProps = {
  label: string;
  onClick: () => void;
  ariaLabel?: string;
};

export function TimeChip({ label, onClick, ariaLabel }: TimeChipProps) {
  return <button type="button" className="ui-time-chip" aria-label={ariaLabel} onClick={onClick}>{label}</button>;
}
