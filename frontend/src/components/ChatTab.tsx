
import { useT } from "../i18n";

export function ChatTab() {
  const { t } = useT();
  return <p className="meeting-chat-notice">{t("meeting:chatUnavailable")}</p>;
}
