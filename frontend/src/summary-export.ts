import type { MeetingSummary, SummaryBlock, SummaryKeyPoint } from "@sauri/shared-types";
import { copy } from "./copy/es";

export function isBlock(point: SummaryKeyPoint | SummaryBlock | string): point is SummaryBlock {
  return typeof point !== "string" && "title" in point;
}

// The exact plain text that "Copy" puts on the clipboard and every summary download saves. It never
// carries minutes or timestamps: sources are only offered as links in the panel.
export function summaryPlainText(summary: MeetingSummary): string {
  const text = copy.summary;
  if (summary.schemaVersion !== 2) {
    return [summary.topic, ...summary.keyPoints.map((point) =>
      `- ${typeof point === "string" ? point : isBlock(point) ? point.title : point.text}`,
    )].join("\n");
  }
  const blocks = summary.keyPoints.filter(isBlock).map((block, index) => [
    `${index + 1}. ${block.title}`,
    ...block.items.flatMap((item) => [`- ${item.text}`, ...item.subItems.map((sub) => `  - ${sub}`)]),
  ].join("\n"));
  return [
    `${text.mainTopic}\n${summary.topic}`,
    `${text.detailedKeyPoints}\n${blocks.join("\n\n")}`,
    ...(summary.conclusion ? [`${text.conclusion}\n${summary.conclusion}`] : []),
  ].join("\n\n");
}
