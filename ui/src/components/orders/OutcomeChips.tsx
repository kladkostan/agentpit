import type { Erc1155Token } from "@/types/market";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface OutcomeChipsProps {
  tokens: Erc1155Token[];
  selected: string;
  onSelect: (label: string) => void;
}

export function OutcomeChips({ tokens, selected, onSelect }: OutcomeChipsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {tokens.map(([tokenId, label]) => {
        const isActive = label === selected;
        return (
          <Button
            key={tokenId}
            type="button"
            variant={isActive ? "default" : "outline"}
            size="sm"
            onClick={() => onSelect(label)}
            className={cn("min-w-[5rem]", isActive && "shadow")}
          >
            {label}
          </Button>
        );
      })}
    </div>
  );
}
