import { sendPurchase } from './client';

export function checkout(cart: string) {
  return sendPurchase(cart);
}
