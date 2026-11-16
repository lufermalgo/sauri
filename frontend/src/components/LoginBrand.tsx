import { AudioLines } from "lucide-react";
import { Icon } from "./ui";

/**
 * Brand tile at the top-left of the login card.
 *
 * Placeholder slot: swap the body for the shared `BrandMark` (brand isotype issue) once it is on main.
 * Decorative: the heading already names the product.
 */
export function LoginBrand() {
  return (
    <div className="login-brand" aria-hidden="true">
      <Icon icon={AudioLines} size={22} />
    </div>
  );
}
