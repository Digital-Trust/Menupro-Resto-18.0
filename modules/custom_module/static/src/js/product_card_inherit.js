import { ProductCard } from "@point_of_sale/app/generic_components/product_card/product_card";
import { patch } from "@web/core/utils/patch";

patch(ProductCard.prototype, {
    // Override du click sur la carte produit
    onClick(ev) {
        // Vérifier si le parent ProductScreen est en mode takeaway
        const productScreen = this.env.services.pos.pos.mainScreen.component;
        if (productScreen && productScreen.isTakeawayMode) {
            console.log("Product click disabled: order is takeaway");
            ev.preventDefault();
            ev.stopPropagation();
            return false;
        }
        return super.onClick(...arguments);
    }
});