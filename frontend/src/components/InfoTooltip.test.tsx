import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import InfoTooltip from "./InfoTooltip";

describe("InfoTooltip", () => {
  it("mostra il testo passato ed è raggiungibile da tastiera", () => {
    const { container } = render(<InfoTooltip text="Spiegazione della pagina" />);

    expect(screen.getByText("Spiegazione della pagina")).toBeInTheDocument();
    expect(container.querySelector(".info-tooltip")).toHaveAttribute("tabindex", "0");
  });
});
