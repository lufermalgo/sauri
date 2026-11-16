// Overlay script injected on demand into the tab being recorded (any web page except
// Meet, whose static content script already hosts it). It carries no page detection.
import { installOverlayMessaging } from "./messaging";

installOverlayMessaging();
