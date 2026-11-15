import { useId, useRef, type ReactNode } from "react";

export type TabsProps = {
  tabs: { id: string; label: ReactNode; panel: ReactNode }[];
  activeId: string;
  onChange: (id: string) => void;
  "aria-label"?: string;
  "aria-labelledby"?: string;
};

export function Tabs({ tabs, activeId, onChange, ...label }: TabsProps) {
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  return <div className="ui-tabs">
    <div {...label} role="tablist" className="ui-tab-list">
      {tabs.map((tab, index) => <button key={tab.id} type="button" role="tab"
        id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`}
        aria-selected={activeId === tab.id} tabIndex={activeId === tab.id ? 0 : -1}
        ref={element => { buttons.current[index] = element; }}
        className="ui-tab" onClick={() => onChange(tab.id)} onKeyDown={event => {
          let next: number;
          switch (event.key) {
            case "ArrowRight": next = (index + 1) % tabs.length; break;
            case "ArrowLeft": next = (index + tabs.length - 1) % tabs.length; break;
            case "Home": next = 0; break;
            case "End": next = tabs.length - 1; break;
            default: return;
          }
          event.preventDefault();
          onChange(tabs[next].id);
          buttons.current[next]?.focus();
        }}>{tab.label}</button>)}
    </div>
    {tabs.map((tab, index) => <div key={tab.id} role="tabpanel" tabIndex={0}
      id={`${id}-panel-${index}`} aria-labelledby={`${id}-tab-${index}`}
      hidden={activeId !== tab.id} className="ui-tab-panel">{tab.panel}</div>)}
  </div>;
}
