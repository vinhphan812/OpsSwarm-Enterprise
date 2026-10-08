import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { useUiStore } from "@/state/ui.store";

/** `?product=P001` opens the page with that product selected. */
export function useProductParam() {
  const [params] = useSearchParams();
  const productId = params.get("product");
  useEffect(() => {
    if (productId) useUiStore.getState().select(productId);
  }, [productId]);
}
