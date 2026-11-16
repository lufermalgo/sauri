import { expect } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { panelCopy as copy } from "./copy";

export function sourceTrigger() {
  return within(screen.getByRole("group", { name: copy.sourceMenu })).getAllByRole("button")[0];
}
export async function chooseSource(label: string) {
  await screen.findByRole("group", { name: copy.sourceMenu });
  if (sourceTrigger().textContent === label) return;
  fireEvent.click(sourceTrigger());
  const item = await screen.findByRole("menuitemradio", { name: label });
  await waitFor(() => expect(item).toBeEnabled());
  fireEvent.click(item);
}
