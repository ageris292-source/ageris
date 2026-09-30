"use client";

import { BellPlus, ListChecks, NotebookPen, Plus } from "lucide-react";
import { useState } from "react";
import { JournalEditor, JournalList, useJournal } from "@/components/Journal";
import { NewPriceAlertDialog, PriceAlertList } from "@/components/PriceAlerts";
import { ListMembership } from "@/components/Watchlist";
import { Button, Card } from "@/components/ui/core";

/** Your own tracking for one stock: lists, price alerts and journal notes. */
export function StockPersonal({ ticker, lastClose }: { ticker: string; lastClose: number | null }) {
  const [newAlert, setNewAlert] = useState(false);
  const [newNote, setNewNote] = useState(false);
  const { items, error } = useJournal({ ticker });

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="min-w-0 space-y-6">
        <Card title={<span className="flex items-center gap-2"><ListChecks size={15} aria-hidden /> Your lists</span>} description="Tap a list to add or remove this stock.">
          <ListMembership ticker={ticker} />
        </Card>
        <Card
          title={<span className="flex items-center gap-2"><BellPlus size={15} aria-hidden /> Price alerts</span>}
          description="Checked at each new daily close. Informational only."
          actions={
            <Button size="sm" icon={<Plus size={14} />} onClick={() => setNewAlert(true)}>
              Add
            </Button>
          }
        >
          <PriceAlertList ticker={ticker} compact />
        </Card>
      </div>
      <Card
        className="xl:col-span-2"
        title={<span className="flex items-center gap-2"><NotebookPen size={15} aria-hidden /> Your notes</span>}
        description="Private research notes and journal entries for this stock."
        actions={
          <Button size="sm" variant="primary" icon={<Plus size={14} />} onClick={() => setNewNote(true)}>
            New note
          </Button>
        }
      >
        <JournalList items={items} error={error} showStock={false} />
      </Card>
      <NewPriceAlertDialog open={newAlert} onClose={() => setNewAlert(false)} ticker={ticker} lastClose={lastClose} />
      <JournalEditor open={newNote} onClose={() => setNewNote(false)} ticker={ticker} />
    </div>
  );
}
