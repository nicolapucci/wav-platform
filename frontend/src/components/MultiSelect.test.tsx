import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MultiSelect, { type MultiSelectOption } from "./MultiSelect";

const OPTIONS: MultiSelectOption[] = [
  { id: "1", label: "Alice" },
  { id: "2", label: "Bob" },
  { id: "3", label: "Carol" },
];

describe("MultiSelect - modalità opzioni statiche", () => {
  it("mostra le opzioni filtrate al focus, escludendo quelle già selezionate", async () => {
    const user = userEvent.setup();
    render(<MultiSelect label="Assegnatari" selected={[OPTIONS[0]]} onChange={vi.fn()} options={OPTIONS} />);

    await user.click(screen.getByRole("textbox"));

    // "Alice" compare comunque come chip selezionata: qui si verifica che non
    // compaia ANCHE come opzione nel dropdown (una sola occorrenza totale).
    expect(screen.getAllByText("Alice")).toHaveLength(1);
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Carol")).toBeInTheDocument();
  });

  it("selezionare un'opzione chiama onChange aggiungendola e pulisce l'input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MultiSelect label="Assegnatari" selected={[]} onChange={onChange} options={OPTIONS} />);

    await user.click(screen.getByRole("textbox"));
    await user.click(screen.getByText("Bob"));

    expect(onChange).toHaveBeenCalledWith([OPTIONS[1]]);
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("rimuovere una chip chiama onChange senza quell'opzione", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MultiSelect label="Assegnatari" selected={[OPTIONS[0], OPTIONS[1]]} onChange={onChange} options={OPTIONS} />,
    );

    await user.click(screen.getByRole("button", { name: "Rimuovi Alice" }));

    expect(onChange).toHaveBeenCalledWith([OPTIONS[1]]);
  });

  it("digitando filtra le opzioni per label (case-insensitive)", async () => {
    const user = userEvent.setup();
    render(<MultiSelect label="Assegnatari" selected={[]} onChange={vi.fn()} options={OPTIONS} />);

    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.type(input, "bo");

    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    expect(screen.queryByText("Carol")).not.toBeInTheDocument();
  });
});

describe("MultiSelect - modalità ricerca async", () => {
  beforeEach(() => {
    // solo setTimeout/clearTimeout (il debounce): con toFake di default,
    // React 18 usa MessageChannel per il suo scheduler interno e finiva
    // anche lui "congelato", con gli aggiornamenti di stato mai flushati.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("mostra un suggerimento finché non si raggiunge minSearchLength, poi fa il debounce prima di chiamare onSearch", async () => {
    const onSearch = vi.fn().mockResolvedValue([{ id: "9", label: "Risultato" }]);
    render(
      <MultiSelect label="Cerca" selected={[]} onChange={vi.fn()} onSearch={onSearch} minSearchLength={2} />,
    );

    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "r" } });

    expect(screen.getByText("Continua a digitare...")).toBeInTheDocument();
    expect(onSearch).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "ri" } });
    expect(screen.getByText("Ricerca...")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(250);

    // niente waitFor qui: con setTimeout fake, il suo polling interno (anche
    // lui su setTimeout) non scatterebbe mai finché il clock non avanza
    // ulteriormente - advanceTimersByTimeAsync flush già sia il debounce sia
    // la promise di onSearch, l'assert è vero da subito.
    expect(onSearch).toHaveBeenCalledWith("ri");
    expect(screen.getByText("Risultato")).toBeInTheDocument();
  });

  it("non richiama onSearch se la query cambia prima dello scadere del debounce", async () => {
    const onSearch = vi.fn().mockResolvedValue([]);
    render(
      <MultiSelect label="Cerca" selected={[]} onChange={vi.fn()} onSearch={onSearch} minSearchLength={2} />,
    );

    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "ri" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.change(input, { target: { value: "ric" } });
    await vi.advanceTimersByTimeAsync(100); // in totale 200ms dal primo cambio, ancora sotto i 250ms di debounce

    expect(onSearch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(150); // completa i 250ms dall'ultimo cambio ("ric")
    expect(onSearch).toHaveBeenCalledTimes(1);
    expect(onSearch).toHaveBeenCalledWith("ric");
  });
});
