/** Icona "?" che mostra un testo (di solito la spiegazione di una pagina, al
 * posto del sottotitolo fisso sotto il titolo) al passaggio del mouse o al
 * focus da tastiera. */
export default function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="info-tooltip" tabIndex={0}>
      ?<span className="info-tooltip-bubble">{text}</span>
    </span>
  );
}
