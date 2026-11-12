// A model chain (verify, photos, plan, extract): tried top to bottom. Drag to reorder, add, remove,
// and give a model its own timeout / temperature (empty = the chain's value).
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useRef, useState } from "react";

export type ModelEntry = { provider: string; model: string; fallback_model?: string | null; timeout_sec?: number | null; temperature?: number | null };

const input = "rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-100";

function optionalNumber(value: string): number | null {
  return value.trim() === "" || Number.isNaN(Number(value)) ? null : Number(value);
}

export function EntryFields({ entry, providers, onChange, withFallback }: {
  entry: ModelEntry; providers: string[]; onChange: (entry: ModelEntry) => void; withFallback?: boolean;
}) {
  return (
    <>
      <select className={input} value={entry.provider} onChange={(e) => onChange({ ...entry, provider: e.target.value })}>
        {providers.map((p) => <option key={p}>{p}</option>)}
      </select>
      <input className={`${input} min-w-0 flex-1`} placeholder="model name" value={entry.model}
        onChange={(e) => onChange({ ...entry, model: e.target.value })} />
      {withFallback && (
        <input className={`${input} w-48`} placeholder="fallback model" value={entry.fallback_model ?? ""}
          onChange={(e) => onChange({ ...entry, fallback_model: e.target.value || null })} />
      )}
      <input className={`${input} w-24`} type="number" min={1} placeholder="timeout s" title="Timeout in seconds for this model; empty = the chain's timeout"
        value={entry.timeout_sec ?? ""} onChange={(e) => onChange({ ...entry, timeout_sec: optionalNumber(e.target.value) })} />
      <input className={`${input} w-24`} type="number" min={0} max={2} step={0.1} placeholder="temp" title="Temperature for this model; empty = models.temperature"
        value={entry.temperature ?? ""} onChange={(e) => onChange({ ...entry, temperature: optionalNumber(e.target.value) })} />
    </>
  );
}

function Row({ id, position, entry, providers, onChange, onRemove }: {
  id: number; position: number; entry: ModelEntry; providers: string[]; onChange: (entry: ModelEntry) => void; onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <li ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex items-center gap-2 rounded border border-neutral-800 bg-neutral-950 p-2 ${isDragging ? "opacity-60" : ""}`}>
      <button type="button" {...attributes} {...listeners} title="Drag to reorder" className="cursor-grab px-1 text-neutral-500 hover:text-neutral-200">⠿</button>
      <span className="w-5 text-xs text-neutral-500">{position}</span>
      <EntryFields entry={entry} providers={providers} onChange={onChange} />
      <button type="button" onClick={onRemove} title="Remove" className="px-2 text-neutral-500 hover:text-red-400">✕</button>
    </li>
  );
}

export function ChainEditor({ entries, providers, onChange }: {
  entries: ModelEntry[]; providers: string[]; onChange: (entries: ModelEntry[]) => void;
}) {
  // dnd-kit needs a stable id per row; entries themselves carry none
  const nextId = useRef(entries.length);
  const [ids, setIds] = useState(() => entries.map((_, i) => i));
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  function dragEnd(event: DragEndEvent) {
    const from = ids.indexOf(Number(event.active.id));
    const to = event.over ? ids.indexOf(Number(event.over.id)) : -1;
    if (from < 0 || to < 0 || from === to) return;
    setIds(arrayMove(ids, from, to));
    onChange(arrayMove(entries, from, to));
  }
  function add() {
    setIds([...ids, nextId.current++]);
    onChange([...entries, { provider: providers[0], model: "", timeout_sec: null, temperature: null }]);
  }
  function remove(index: number) {
    setIds(ids.filter((_, i) => i !== index));
    onChange(entries.filter((_, i) => i !== index));
  }

  return (
    <div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          <ul className="space-y-1">
            {entries.map((entry, i) => (
              <Row key={ids[i]} id={ids[i]} position={i + 1} entry={entry} providers={providers}
                onChange={(changed) => onChange(entries.map((e, j) => (j === i ? changed : e)))} onRemove={() => remove(i)} />
            ))}
          </ul>
        </SortableContext>
      </DndContext>
      <button type="button" onClick={add} className="mt-2 rounded bg-neutral-800 px-2 py-1 text-xs hover:bg-neutral-700">+ Add model</button>
    </div>
  );
}
