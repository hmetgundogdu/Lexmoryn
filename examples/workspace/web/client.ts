export function sendPurchase(cart: string) {
  // Browser gateway sends an order to the transaction endpoint.
  return { endpoint: '/transactions', cart };
}
