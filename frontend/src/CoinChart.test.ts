import { expect, it } from "vitest";
import { validCandles } from "./CoinChart";
it("charts only finite positive recorded OHLC prices in chronological order", () => {
  const first={timestamp:"2026-10-26T10:00:00Z",open:"1",high:"2",low:".8",close:"1.1"};
  const second={...first,timestamp:"2026-10-26T10:05:00Z"};
  expect(validCandles([second,{...first,close:"NaN"},{...first,timestamp:"invalid"},{...first,low:"-1"},first])).toEqual([first,second]);
});
