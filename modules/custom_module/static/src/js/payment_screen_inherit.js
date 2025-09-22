/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(PaymentScreen.prototype, {
  setup() {
    super.setup();
    this.pos = usePos();
    this.notification = useService("notification"); 
    this.orm = useService("orm");

    onMounted(() => {
      this.autoSelectPaymentMethodForPaidOnline();
    });
  },

  async autoSelectPaymentMethodForPaidOnline() {
    try {
      const currentOrder = this.pos.get_order();
      if (!currentOrder) return;

      if (currentOrder.paid_online) {
        console.log(
          "🔄 Commande payée en ligne détectée - Présélection de la méthode de paiement"
        );

        const onlinePaymentMethod = await this.findOnlinePaymentMethod();

        if (onlinePaymentMethod) {
          await this.addNewPaymentLine(onlinePaymentMethod);

          if (this.notification) {
            this.notification.add(
              `💳 Méthode de paiement présélectionnée: ${onlinePaymentMethod.name}`,
              3000,
              { type: "info" }
            );
          }

          console.log(
            `✅ Méthode de paiement présélectionnée: ${onlinePaymentMethod.name}`
          );
        } else {
          console.warn(
            "⚠️ Aucune méthode de paiement en ligne trouvée ou créée"
          );
        }
      }
    } catch (error) {
      console.error("❌ Erreur lors de la présélection de paiement:", error);
    }
  },

  async getOnlinePaymentDefaultAccountIds() {
    try {
      const defaultIds = await this.orm.call(
        "pos.payment.method",
        "get_default_online_payment_account_ids",
        [],
        {}
      );
      return defaultIds;
    } catch (error) {
      console.error(
        "❌ Erreur lors de la récupération des IDs de compte par défaut:",
        error
      );
      return { journal_id: false, receivable_account_id: false };
    }
  },

  async findOnlinePaymentMethod() {
    try {
      const menuproMethod = this.payment_methods_from_config.find(
        (method) => method.name === "Online Menupro"
      );

      if (menuproMethod) {
        console.log("✅ Méthode 'Online Menupro' trouvée:", menuproMethod);
        return menuproMethod;
      }

      console.log(
        "🔄 Méthode 'Online Menupro' non trouvée - Tentative de création via backend..."
      );

      const defaultAccountIds = await this.getOnlinePaymentDefaultAccountIds();
      const journalId = defaultAccountIds.journal_id;
      const receivableAccountId = defaultAccountIds.receivable_account_id;

      if (!journalId || !receivableAccountId) {
        console.error(
          "❌ Impossible de créer 'Online Menupro': Journal ou compte à recevoir par défaut non trouvé."
        );
        return null;
      }

      const newMethodId = await this.orm.call(
        "pos.payment.method",
        "create_online_menupro_payment_method_rpc",
        [this.pos.config.id, journalId, receivableAccountId],
        {}
      );

      if (newMethodId) {
        console.log(
          `✅ Backend a créé la méthode 'Online Menupro' avec ID: ${newMethodId}. Rechargement des méthodes de paiement...`
        );
        await this.pos.load_server_data(); // This reloads all POS data, including payment methods

        const newlyLoadedMethod = this.pos.payment_methods.find(
          (method) => method.id === newMethodId
        );
        if (newlyLoadedMethod) {
          this.payment_methods_from_config = this.pos.config.payment_method_ids
            .slice()
            .sort((a, b) => a.sequence - b.sequence);
          console.log("✅ Méthode 'Online Menupro' rechargée et disponible.");
          return newlyLoadedMethod;
        } else {
          console.error(
            "❌ Méthode 'Online Menupro' créée mais non trouvée après rechargement."
          );
          return null;
        }
      }

      console.log(
        "⚠️ Création échouée - Recherche de méthodes alternatives..."
      );
      return this.findAlternativeOnlinePaymentMethod();
    } catch (error) {
      console.error(
        "❌ Erreur lors de la recherche/création de méthode de paiement:",
        error
      );
      return null;
    }
  },

  findAlternativeOnlinePaymentMethod() {
    try {
      const onlineMethods = this.payment_methods_from_config.filter(
        (method) => {
          return (
            method.name.toLowerCase().includes("online") ||
            method.name.toLowerCase().includes("menupro") ||
            method.payment_method_type === "card" ||
            method.payment_method_type === "online" ||
            method.is_online_payment ||
            method.use_payment_terminal ||
            method.menupro_online_payment
          );
        }
      );

      if (onlineMethods.length > 0) {
        console.log("✅ Méthode alternative trouvée:", onlineMethods[0].name);
        return onlineMethods[0];
      }

      if (this.payment_methods_from_config.length > 0) {
        console.log(
          "⚠️ Utilisation de la première méthode disponible:",
          this.payment_methods_from_config[0].name
        );
        return this.payment_methods_from_config[0];
      }

      console.warn("❌ Aucune méthode de paiement disponible");
      return null;
    } catch (error) {
      console.error(
        "❌ Erreur lors de la recherche de méthodes alternatives:",
        error
      );
      return null;
    }
  },

  isOnlinePaymentMethod(paymentMethod) {
    try {
      if (!paymentMethod || !paymentMethod.name) {
        return false;
      }

      if (paymentMethod.name === "Online Menupro") {
        return true;
      }

      return (
        paymentMethod.name.toLowerCase().includes("online") ||
        paymentMethod.name.toLowerCase().includes("menupro") ||
        paymentMethod.payment_method_type === "card" ||
        paymentMethod.payment_method_type === "online" ||
        paymentMethod.is_online_payment ||
        paymentMethod.use_payment_terminal ||
        paymentMethod.menupro_online_payment
      );
    } catch (error) {
      console.error(
        "❌ Erreur lors de la vérification de méthode de paiement:",
        error
      );
      return false;
    }
  },

  async addNewPaymentLine(paymentMethod) {
    const currentOrder = this.pos.get_order();

    if (!paymentMethod) {
      console.error("❌ Méthode de paiement non définie");
      return false;
    }

    // Empêcher l'ajout de méthodes non autorisées selon le statut paid_online
    if (currentOrder?.paid_online && paymentMethod.name !== "Online Menupro") {
      console.warn(
        `🚫 Payment method "${
          paymentMethod.name || "unknown"
        }" disabled for online paid orders`
      );

      if (this.notification) {
        this.notification.add(
          `🚫 Seule la méthode "Online Menupro" est disponible pour les commandes payées en ligne`,
          3000,
          { type: "warning" }
        );
      }

      return false;
    }

    // Empêcher l'ajout de "Online Menupro" aux commandes normales
    if (
      currentOrder &&
      !currentOrder.paid_online &&
      paymentMethod.name === "Online Menupro"
    ) {
      console.warn(
        `🚫 Payment method "Online Menupro" disabled for normal orders`
      );

      if (this.notification) {
        this.notification.add(
          `🚫 La méthode "Online Menupro" est réservée aux commandes payées en ligne`,
          3000,
          { type: "warning" }
        );
      }

      return false;
    }

    if (currentOrder?.paid_online) {
      console.log(
        `💳 Adding payment line for online paid order: ${
          paymentMethod.name || "unknown"
        }`
      );
    } else if (currentOrder && !currentOrder.paid_online) {
      console.log(
        `💳 Adding payment line for normal order: ${
          paymentMethod.name || "unknown"
        }`
      );
    }

    return await super.addNewPaymentLine(paymentMethod);
  },
});
