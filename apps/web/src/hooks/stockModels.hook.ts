import { useEffect, useState } from "react";
import { ASSETS_MODE } from "@/enums/stock.enum";
import { NO_MODELS, assetsMode, loadStockModels, type StockModels } from "@/scene/entities/stock/models";

/**
 * The stock GLB models, once they have loaded. Until then, under `?assets=primitive`, and
 * for any model that fails, stock is drawn as primitives, so the scene never waits on them.
 */
export function useStockModels(): StockModels {
  const [models, setModels] = useState<StockModels>(NO_MODELS);
  useEffect(() => {
    if (assetsMode() === ASSETS_MODE.Primitive) return;
    let live = true;
    void loadStockModels().then((loaded) => {
      if (live) setModels(loaded);
    });
    return () => {
      live = false;
    };
  }, []);
  return models;
}
