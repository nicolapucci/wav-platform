import { useEffect, useRef, useState } from "react";

export type MultiSelectOption = { id: string; label: string };

type Props = {
  label: string;
  selected: MultiSelectOption[];
  onChange: (selected: MultiSelectOption[]) => void;
  // modalità statica: filtro client-side su questa lista fissa...
  options?: MultiSelectOption[];
  // ...oppure modalità ricerca: risolta lato server man mano che si digita
  // (debounce interno). Le due modalità sono alternative, non combinate.
  onSearch?: (query: string) => Promise<MultiSelectOption[]>;
  placeholder?: string;
  minSearchLength?: number;
};

/** Combobox multi-selezione: chip per le scelte fatte + input con dropdown a
 * comparsa, in sostituzione di <select multiple> (richiede ctrl/cmd+click,
 * poco leggibile) usato finora nei filtri. */
export default function MultiSelect({
  label,
  selected,
  onChange,
  options,
  onSearch,
  placeholder,
  minSearchLength = 2,
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [searchResults, setSearchResults] = useState<MultiSelectOption[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedIds = new Set(selected.map((o) => o.id));

  useEffect(() => {
    if (!onSearch) return;
    if (query.length < minSearchLength) {
      setSearchResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const timeout = setTimeout(async () => {
      const results = await onSearch(query);
      setSearchResults(results);
      setSearching(false);
    }, 250);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, onSearch, minSearchLength]);

  const results = (options ? options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase())) : searchResults).filter(
    (o) => !selectedIds.has(o.id),
  );

  function handleSelect(option: MultiSelectOption) {
    onChange([...selected, option]);
    setQuery("");
    inputRef.current?.focus();
  }

  function handleRemove(id: string) {
    onChange(selected.filter((o) => o.id !== id));
  }

  const showHint = Boolean(onSearch) && query.length > 0 && query.length < minSearchLength;
  const dropdownVisible = open && (searching || showHint || results.length > 0 || query.length > 0 || !onSearch);

  return (
    <div className="field multiselect">
      <label>{label}</label>
      <div className="multiselect-control" onClick={() => inputRef.current?.focus()}>
        {selected.map((o) => (
          <span key={o.id} className="chip">
            {o.label}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleRemove(o.id);
              }}
              aria-label={`Rimuovi ${o.label}`}
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          className="multiselect-input"
          value={query}
          placeholder={selected.length === 0 ? placeholder : ""}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      </div>
      {dropdownVisible && (
        <div className="multiselect-dropdown">
          {searching && <div className="multiselect-empty">Ricerca...</div>}
          {!searching && showHint && <div className="multiselect-empty">Continua a digitare...</div>}
          {!searching &&
            !showHint &&
            results.map((o) => (
              <div
                key={o.id}
                className="multiselect-option"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleSelect(o)}
              >
                {o.label}
              </div>
            ))}
          {!searching && !showHint && results.length === 0 && (
            <div className="multiselect-empty">Nessun risultato</div>
          )}
        </div>
      )}
    </div>
  );
}
