import { BrandMark } from "./ui";

/**
 * Brand mark at the top-left of the login card.
 * Decorative: the heading already names the product.
 */
export function LoginBrand() {
  return (
    <div className="login-brand">
      <BrandMark size={48} />
    </div>
  );
}
