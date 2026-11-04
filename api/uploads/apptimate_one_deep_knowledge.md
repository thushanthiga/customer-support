# Apptimate One — Complete Enterprise Platform Deep Knowledge Base

**Version Generated At**: 2026-10-15 09:51:18

This master documentation provides an exhaustive, inch-by-inch breakdown of every module, UI feature, workflow, modal, table column, API endpoint, and backend business validation across the entire Apptimate One SaaS ERP platform.

---

## Platform Architecture & Table of Modules

1. [Module: Sales & Commercial Operations](#module-sales)
2. [Module: Inventory & Stock Management](#module-inventory)
3. [Module: Procurement & Supplier Management](#module-procurement)
4. [Module: Finance & General Accounting](#module-finance)
5. [Module: Human Resources & Payroll](#module-hr)
6. [Module: Jewelry Industry Vertical](#module-jewelry)
7. [Module: Construction & Project Management](#module-construction)
8. [Module: Money Exchange & Foreign Remittances](#module-money-exchange)
9. [Module: Customer Relationship Management (CRM)](#module-crm)
10. [Module: Production & Manufacturing](#module-production)
11. [Module: Reporting & Business Intelligence](#module-reporting)
12. [Module: AI Analytics & Demand Forecasting](#module-ai-analytics)
13. [Module: Core Platform Administration & Multi-Tenancy](#module-core)

---

<a name="module-sales"></a>
## Module: SALES

## Feature: INVOICES

# Sales Invoices — UI and Workflow Guide

## 1. Global navigation and entry flow

The provided global menu lists **Sales Invoices** under **Sales → Post-Sales**, at:

- **Route:** `/sales/invoices`
- **Menu label:** Sales Invoices
- **Menu key:** `sales__invoices`

This page is therefore a listed Sales menu page, not a hidden/internal route.

The page concerns accounts receivable: it lists sales invoices, displays their payment status and balances, and lets a user open invoice details and log a payment for an invoice that is not marked paid.

**CRITICAL NOTE**: This is a view-only page. Users cannot manually create a invoices here.

This note applies to creating invoice records: the supplied page contains no invoice-creation form or button. It does, however, provide a **Log Payment** workflow for eligible existing invoices.

## 2. Overview

The page displays invoices fetched with parameters that identify sales-related accounts-receivable invoices. Users can:

- Browse a paginated invoice list.
- Filter the list by payment status.
- Search by invoice number or customer using a search popover.
- Open an invoice’s detail modal.
- Review its balance and, when payment history is present, its payment history.
- Open a payment form for an invoice whose status is not `paid`.
- Record one or more payment entries against that invoice through the payment form.

The code does not show a workflow for creating, editing, deleting, voiding, or issuing invoices.

## 3. Page layout and visible elements

### 3.1 Page heading

At the top of the page, the heading reads **Sales Invoices**.

When the invoice list is **not loading**, a `RecordCount` component is rendered with the current `totalItems` value. The component’s internal presentation is not included in the supplied code, so its exact visual format cannot be specified.

Below the heading, the page displays:

> Accounts receivable — track invoices and collect payments.

### 3.2 Status filter controls

The page renders four buttons:

| Button text | Filter value |
|---|---|
| All | Empty string |
| Unpaid | `unpaid` |
| Partial | `partially_paid` |
| Paid | `paid` |

The currently selected filter receives the active styling. Clicking a filter sets the filter value and resets the current page to page 1. Changing the filter triggers invoice fetching through the page’s fetch effect.

### 3.3 Search control

The page renders a `DesktopSearchPopover` with:

- **Placeholder:** `Search by invoice #, customer...`
- Its current search value connected to `searchTerm`.
- Its change handler connected to `setSearchTerm`.

Typing does not immediately update the search parameter sent to the invoice API. A 500 ms debounce updates `debouncedSearch`, then resets the page to page 1. The popover’s internal layout and any additional controls are not shown in the supplied code.

### 3.4 Invoice table

The table has eight columns:

1. **Invoice #**
2. **Ref#**
3. **Customer**
4. **Date**
5. **Amount Due**
6. **Received**
7. **Outstanding**
8. **Status**

When the request is loading, the table renders `TLoader` with `cols={8}`.

When loading has finished and there are no invoices, the table shows an `EmptyState` with the message:

> No invoices found.

When invoices are present, each invoice appears as a clickable row. Clicking anywhere on the row opens the invoice-detail flow.

The values shown in each row are:

- **Invoice #:** `inv.invoice_number`
- **Ref#:** `inv.source_reference_no`, or `-` if absent
- **Customer:** `inv.party?.full_name`, or `-` if absent
- **Date:** `inv.invoice_date` formatted using the browser’s `toLocaleDateString()`, or `-` if absent
- **Amount Due:** `inv.amount_due`, formatted with two minimum decimal places
- **Received:** `inv.amount_settled`, formatted with two minimum decimal places
- **Outstanding:** `amount_due - amount_settled`, with missing/falsy values treated as zero before numeric conversion; it is formatted with two minimum decimal places
- **Status:** a badge based on the status mapping below

The amount formatter converts the value to a number, uses zero for a falsy input, and calls `toLocaleString` with `minimumFractionDigits: 2`. No currency symbol is added by this formatter.

#### Status labels and colors

| Invoice status value | Display label | Badge color |
|---|---|---|
| `unpaid` | Unpaid | danger |
| `partially_paid` | Partial | warning |
| `paid` | Paid | success |

If the status value is not in the mapping, the page uses the **Unpaid** label and danger color as its fallback. This is a UI fallback; the code does not show that the underlying invoice status is changed.

The Outstanding amount is styled red when it is greater than zero, and gray otherwise. This is a display rule based on the calculated balance.

### 3.5 Pagination

Pagination is rendered only when both conditions are true:

- The list is not loading.
- There is at least one invoice in the current result set.

It receives:

- `currentPage={page}`
- `totalItems={totalItems}`
- `itemsPerPage={15}`
- `onPageChange={setPage}`

The pagination component’s internal controls and exact wording are not included in the supplied code. Changing the page updates `page`, which triggers another invoice fetch.

## 4. Invoice detail modal

Clicking an invoice row immediately sets that row as the invoice being viewed, opening the detail modal with the row data. The page then calls `getInvoice(inv.id)`. If that request succeeds and returns a result, the modal content is updated to use the returned invoice detail. Errors in this detail request are silently ignored by the supplied code.

The modal is an `EntityDetailModal` configured with:

- **Title:** `Invoice Details`
- **Open state:** whether `viewingInvoice` is truthy
- **Entity ID:** `viewingInvoice?.entity_id`
- **Close handler:** clears `viewingInvoice`

The internal visual controls provided by `EntityDetailModal` are not shown, so no additional modal close icon or behavior can be stated from this code.

### 4.1 Invoice identity and status

The detail content displays:

- The invoice number as a heading.
- The customer’s `party.full_name`, or **Unknown** if absent.
- A status badge using the same status-label and color mapping as the table, including the Unpaid fallback for unrecognized statuses.

### 4.2 Balance summary

The detail modal shows four summary items:

1. **Amount Due** — formatted `viewingInvoice.amount_due`
2. **Received** — formatted `viewingInvoice.amount_settled`
3. **Outstanding** — formatted as `Number(amount_due) - Number(amount_settled)`
4. **Due Date** — formatted with `toLocaleDateString()`, or `-` if no due date is present

Unlike the list-row calculation, the detail Outstanding expression directly converts both values with `Number(...)`; the code does not apply the list formatter’s `|| 0` fallback in that expression.

### 4.3 Payment history

The Payment History section appears only if `viewingInvoice.payments?.length > 0`.

Its table has four columns:

- **Date**
- **Method**
- **Amount**
- **By**

For each payment:

- Date is `payment_date` formatted with `toLocaleDateString()`, or `-` if absent.
- Method displays `payment_method`.
- Amount displays `payment_amount` through the page’s two-decimal formatter.
- By displays `creator?.name`, or `-` if absent.

If there are no payments, the code does not render this section or an empty-history message.

### 4.4 Detail-modal actions and status condition

The footer is rendered only when:

```ts
viewingInvoice.status !== "paid"
```

For any status other than exactly `paid`, the footer contains:

- **Close** — clears `viewingInvoice`.
- **Log Payment** — sets the current invoice as `payingInvoice` and clears `viewingInvoice`, opening the payment modal.

For an invoice whose status is exactly `paid`, this footer—and therefore these two footer buttons—is not rendered by this component. Any additional close behavior supplied internally by `EntityDetailModal` is not shown in the provided code.

## 5. Log Payment modal and form

The payment modal is rendered when `payingInvoice` is truthy. It is configured with:

- **Title:** `Log Payment — [invoice number]`
- **Size:** `md`
- **Close handler:** clears `payingInvoice`

The modal contains `PaymentForm`, supplied with the selected invoice, a success callback, a cancel callback, and additional props from the page. The `PaymentForm` implementation shown in the supplied code destructures only `invoice`, `onSuccess`, and `onCancel`; the additional props passed by the page are not used by this implementation.

### 5.1 Payment amount balance used by the form

The form calculates its outstanding amount as:

```ts
Number(invoice.amount_due || 0) -
Number(invoice.amount_settled || invoice.amount_received || 0)
```

This value is passed to `PaymentSection` as `totalAmount`.

The form’s fallback logic means that if `amount_settled` is falsy, it uses `amount_received` if that value is truthy; otherwise it uses zero.

### 5.2 Payment Date

The form contains a required-looking label:

> Payment Date *

It renders a date input whose initial value is:

```ts
new Date().toISOString().split("T")[0]
```

Changing the input updates `paymentDate`. The required asterisk is part of the label; the shown code does not set an HTML `required` attribute on the input.

### 5.3 PaymentSection

The form renders a shared `PaymentSection` with:

- `totalAmount` set to the calculated outstanding amount
- The current `payments` entries
- `setPayments` as the change handler
- A payment-mode fetch callback
- A bank-account lookup callback

The supplied source does **not** include the implementation of `PaymentSection`. Therefore, its internal field labels, inputs, buttons, payment toggles, discount controls, and exact layout cannot be verified from this code and are not specified here.

The payment-mode callback calls `getPaymentModes()`. If the response is successful and `result` is an array, it removes payment modes whose `code`, lowercased, equals `credit`. Other modes are not filtered by the shown callback. Bank-account lookup is passed as `getBankAccountsLookup`.

### 5.4 Remarks

The form contains a **Remarks** label and a textarea with:

- `rows={2}`
- Placeholder: `Optional notes...`
- Initial value: an empty string

Changing the textarea updates the form’s `remarks` value.

### 5.5 Payment-form footer

The form footer contains:

- **Cancel** — calls `onCancel`, which clears `payingInvoice` in the page.
- **Record Payment** — submits the form. It displays the form’s loading state while submission is in progress.

## 6. Step-by-step workflows

### 6.1 Browse and filter invoices

1. Open **Sales Invoices** from the Sales menu at `/sales/invoices`.
2. The page fetches invoices using the current page, search term, and status filter.
3. While fetching, the table displays an eight-column loading placeholder.
4. When results arrive, inspect the invoice number, reference, customer, date, amount due, amount received, outstanding balance, and status.
5. Select **All**, **Unpaid**, **Partial**, or **Paid** to change the status filter.
6. The page resets to page 1 when a status filter is selected.
7. If the current result set contains invoices and the page is not loading, use the pagination component to change pages.

### 6.2 Search invoices

1. Use the search popover with placeholder `Search by invoice #, customer...`.
2. Enter or change the search text.
3. After 500 ms without another change, the page copies the search text into the debounced search value and resets to page 1.
4. The changed debounced search value triggers a new invoice request.

The supplied code does not specify whether the popover has a separate submit action, clear control, or other internal behavior.

### 6.3 Inspect invoice details

1. Click an invoice row.
2. The page immediately opens the detail modal using the row’s invoice data.
3. The page requests the full invoice using `getInvoice(inv.id)`.
4. If the detail request succeeds with a result, the modal updates to that result.
5. Review the invoice number, customer, status, balance summary, due date, and—if present—payment history.
6. If the invoice status is not exactly `paid`, the modal footer provides **Close** and **Log Payment**.
7. For an invoice marked `paid`, this component does not render that footer.

### 6.4 Open the payment form

1. In the detail modal for an invoice whose status is not `paid`, select **Log Payment**.
2. The page stores that invoice in `payingInvoice`.
3. The detail modal state is cleared.
4. The **Log Payment — [invoice number]** modal opens with the payment form.
5. The Payment Date defaults to the current date string generated by the form.
6. Use the `PaymentSection` to provide payment entries; its inner controls are not included in the supplied source.
7. Optionally enter notes in **Remarks**.
8. Select **Cancel** to close the payment modal without submitting, or select **Record Payment** to submit.

### 6.5 Submit payment entries

On submission, the form:

1. Prevents the browser’s default form submission.
2. Checks whether there is at least one payment entry.
   - If there are none, it displays: **Please add at least one payment** and stops.
3. Adds the numeric amounts from the entries, treating an unconvertible/falsy amount as zero for this total.
4. Compares the total with the form’s calculated outstanding amount.
   - If `totalToPay > outstanding + 0.01`, it displays:  
     **Payment amount exceeds outstanding balance ([outstanding to two decimals])**  
     and stops.
5. Sets the submitting state.
6. Iterates over the payment entries.
7. Skips any entry for which `Number(p.amount) <= 0`.
8. For each remaining entry, constructs a payment payload and calls `logPayment`.
9. Counts responses with `res.is_success` as successful. For an unsuccessful response, it displays:  
   **Failed for [mode name]: [response message]**
10. If at least one entry succeeds, it displays **Payment recorded successfully**, calls `onSuccess`, closes the payment modal, and triggers a fresh invoice-list fetch.
11. If an exception is thrown, it displays the exception message or **Error recording payment**.
12. In all cases, the submitting state is cleared in `finally`.

The code does not show a success callback that refreshes the currently open invoice detail; the success callback closes the payment modal and fetches the invoice list.

## 7. API calls and data flow

### 7.1 Invoice list request

The page calls `getInvoices` with:

- `page`: current page number
- `per_page`: `15`
- `search`: debounced search text
- `type`: `ar`
- `document_type`: `invoice`
- `source`: `sales_order,pos`
- `transaction_category`: `sales`
- `status`: included only when a status filter is selected

When the response has `is_success` and a truthy `result`, the page:

- Sets the rows from `res.result.data || []`.
- Sets the total from `res.result.meta?.total`, falling back to `res.result.total`, then `0`.

If this request throws, the page displays the exception message or **Failed to load**. The loading state is cleared in `finally`.

### 7.2 Invoice detail request

Selecting a row calls `getInvoice(inv.id)`. A successful response with a result replaces the selected row object with the returned invoice detail. Exceptions are caught and ignored in this detail-loading path.

### 7.3 Payment-mode and bank-account lookups

The form’s `PaymentSection` receives callbacks for:

- `getPaymentModes()`, with the `credit` mode filtered out from a successful array result.
- `getBankAccountsLookup`.

The supplied code does not show the implementations or response shapes for these lookup functions beyond the payment-mode filtering described above.

### 7.4 Payment recording request

For each positive payment entry, the form calls `logPayment` with a payload containing:

- `sales_invoice_id`: `invoice.id`
- `payment_date`: the form’s Payment Date
- `payment_amount`: `p.amount`
- `payment_method`: `p.mode_code`
- `payment_mode_id`: `p.mode_id`
- `remarks`: the remarks text, or `null` when empty

When `p.metadata` exists:

- `reference` is added to the payload if present.
- `bank_account_id` is added if present.
- The complete metadata object is assigned to `mode_metadata`.

A failed response produces a toast for that payment mode. The code continues iterating through the other payment entries.

### 7.5 Props passed to `PaymentForm`

The page passes `onRecordPayment`, `fetchPaymentModes`, and `fetchBankAccounts` in addition to the invoice and callbacks. The displayed `PaymentForm` definition only destructures `invoice`, `onSuccess`, and `onCancel`, and the payment form uses its own `logPayment`, `getPaymentModes`, and `getBankAccountsLookup` references. The additional passed props are not consumed in the shown form implementation.

## 8. Validation and business rules evidenced by this code

The following are rules explicitly implemented in the supplied frontend code:

- Payment submission is stopped when the payment-entry array is empty.
- The combined amount is rejected when it exceeds the calculated outstanding amount by more than `0.01`.
- Payment entries with an amount that converts to zero or a negative number are skipped when requests are sent.
- The payment-mode lookup excludes a mode whose code lowercases to `credit`.
- The **Log Payment** footer action is shown only when the invoice status is not exactly `paid`.
- The detail payment-history section is shown only when the invoice has at least one payment.
- The invoice list displays at most the page size requested in its parameters—15 per page—while the precise pagination behavior belongs to the shared `Pagination` component.
- An unrecognized invoice status is presented using the Unpaid badge fallback.
- Search is debounced by 500 ms in the UI.
- The code does not set an HTML `required` attribute on the Payment Date input, despite showing an asterisk in its label.

These are frontend behaviors visible in the provided code. No extracted backend validation section or backend implementation was supplied, so backend-enforced requirements, limits, permissions, and business rules cannot be established here. In particular, no additional maximum payment amount, discount limit, or backend validation rule should be inferred from this source.

## 9. Scope and unavailable component details

No `ProductTransactionScreen` is used in the supplied invoice page or payment form, so no product-transaction fields are applicable here.

The implementations of `DesktopSearchPopover`, `RecordCount`, `Pagination`, `EntityDetailModal`, `PaymentSection`, and the table primitives are not included. Their internal controls or presentation cannot be documented beyond the props and rendered content shown above.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---

## Feature: RETURNS

# Sales Returns — UI and Workflow Guide

## 1. Global navigation and entry flow

- The global Sales menu contains **Sales Returns**, at **`/sales/returns`**, in the **Post-Sales** group.
- The list page’s explanatory text says: **“Track customer returns and credit notes. Returns are created from Sales Order details.”**
- The list page also has **Create Return** links. In the supplied code, those links point to **`/returns/create`**.
- The create-page code lives at `apps/common-ui/sales-ui/app/returns/create/page.tsx`, and its Cancel actions navigate to **`/returns`**.
- **`/returns/create` is not listed as a separate entry in the supplied global menu.** It is a route linked from the Sales Returns page, not a separately documented sidebar item. The only Sales Returns sidebar entry shown is **Sales Returns** at `/sales/returns`.
- The create flow can also be initialized with query parameters:
  - `source_type`
  - `document_id`
  - `auto_fetch=true`
  
  When a `document_id` is present and `auto_fetch` is exactly `"true"`, the page attempts to fetch the document using the supplied `source_type`, or defaults to `"sales_order"` when that value is absent.

## 2. Feature overview

The feature has two supplied pages:

1. **Sales Returns list and detail view** — displays existing returns, supports search and pagination, and lets the user view or print a return.
2. **Create Sales Return** — selects a completed or partially shipped Sales Order, or a POS Sale, loads its returnable dispatched lines, captures return details, and submits a return. It can also collect payment details for an immediate refund.

The list page describes returns as being created from Sales Order details. The create page’s own instructions and transaction selector support both **Sales Orders** and **POS Sales**.

There is no supplied source for other returns-related pages or route variants. The create flow is documented below because it is explicitly linked from the supplied list-page code.

---

# 3. Page: Sales Returns list — `/sales/returns`

## 3.1 Page heading and controls

At the top of the page:

- Heading: **Sales Returns**
- A `RecordCount` is displayed when the list is not loading. The same count component appears in two layout regions in the supplied JSX, so it may be rendered in both responsive/header areas depending on the UI layout.
- Description: **“Track customer returns and credit notes. Returns are created from Sales Order details.”**

### Search and creation controls

The page provides:

- A mobile-oriented `TableMobileOptions` area:
  - Search label: **Search Returns**
  - Search placeholder: **Search by SR #, SO #...**
  - Search value bound to the page’s search term.
  - A **Create Return** button linking to `/returns/create`.
- A desktop search control:
  - `DesktopSearchPopover`
  - Placeholder: **Search by SR #, SO #...**
  - Search value bound to the same search term.
- A second **Create Return** button, also linking to `/returns/create`.

Typing into search updates the search term. The request is debounced for **500 ms**; after the delay, the debounced value is updated and the current page is reset to page 1.

## 3.2 Returns table

The table has eight columns:

1. **SR #**
   - Shows `sr_number`.
2. **SO / POS**
   - Shows the Sales Order number (`sales_order.so_number`) if available.
   - Otherwise shows the POS number (`pos_sale.pos_number`) if available.
   - Otherwise shows `-`.
3. **Customer**
   - Shows `sales_order.customer.name`, or `pos_sale.party.name`, or `pos_sale.party.first_name`, in that order.
   - Otherwise shows `-`.
4. **Warehouse**
   - Shows `warehouse.name`, or `-`.
5. **Return Date**
   - Shows a `DateLabel` for `return_date`, or `-` if absent.
6. **Grand Total**
   - Shows the grand total formatted with two decimal places.
7. **Status**
   - The displayed status is hard-coded as **Completed** with a success badge. The shown list code does not select this label based on a return-status field.
8. **Actions**
   - A dropdown opened by a vertical-more icon.

### Table states

- **Loading:** the table body renders `TLoader` with eight columns.
- **No results:** the table body displays **“No sales returns found. Returns are processed from the Sales Order detail page.”**
- **Results:** each return renders as a clickable row. Clicking the row opens its detail view.
- Clicking within the Actions cell does not trigger the row click because that area stops event propagation.

### Row action menu

Each row’s Actions dropdown contains:

- **View Details** — opens the return detail view.
- **Print** — calls the detail-loading function and schedules printing after 500 ms.

## 3.3 Pagination

When the page is not loading and there is at least one return, a `Pagination` control appears.

- Current page is held in page state.
- The page size is **15**.
- Changing pages updates the page state and triggers another list fetch.
- Total items are taken from response metadata when available, falling back to the response’s top-level total.
- Total pages are taken from response metadata when available, falling back to a top-level `last_page`, then to 1.

## 3.4 Opening a return

A row click or **View Details** calls `openDetail`:

1. The selected row object is placed in `viewingReturn`, so the detail modal can open.
2. `viewLoading` is set to true.
3. The page calls `getSalesReturn(sr.id)`.
4. If the response is successful and contains a result, that result replaces the selected row data.
5. Errors from this detail fetch are silently swallowed in the shown code.
6. `viewLoading` is set to false in the `finally` block.

Although a loading state is maintained, the supplied JSX does not use `viewLoading` to show a loading indicator.

## 3.5 Sales Return Details modal

The detail wrapper is given:

- `isOpen`: whether `viewingReturn` is truthy.
- `onClose`: clears `viewingReturn`.
- Title: **Sales Return Details**
- `entityId`: `viewingReturn.entity_id`

The modal’s rendered contents, when a return is selected, are:

### Return heading area

- A return/rotate icon.
- The return number: `sr_number`.
- Text in the form **“Against [document number]”**:
  - Uses the Sales Order number if available.
  - Otherwise the POS Sale number if available.
  - Otherwise `-`.
- A hard-coded **Completed** success badge.

### Return summary fields

The modal shows these five label/value pairs:

- **Customer**
  - Sales Order customer name, or POS party name, or `-`.
- **Warehouse**
  - Warehouse name, or `-`.
- **Return Date**
  - Localized date if present, or `-`.
- **Grand Total**
  - Formatted to two decimal places.
- **Received By**
  - `received_by.name`, or `-`.

### Return Lines section

This section appears only when `viewingReturn.lines` has at least one entry.

Its table has five columns:

1. **Item**
2. **Qty**
3. **Reason**
4. **Disposition**
5. **Total**

For each line:

- **Item name**
  - Uses `line.item.name`.
  - If there is no item name, shows **“Deleted Item (ID: [item_id])”**.
- **Variant**
  - If the item has variants and a variant is present, the variant name appears in parentheses.
- **Free quantity indicator**
  - A **Free** badge appears when `is_free_qty` is true.
- **Batch**
  - If a batch is present, shows **“Batch: [batch_number]”**.
- **Serial number**
  - If `gin_line.serial_number.serial_number` is present, shows **“SN: [serial number]”**.
- **Free quantity parent information**
  - If the line is free quantity and has parent line names, shows **“For: [comma-separated parent line names]”**.
- **Quantity**
  - Shows the numeric return quantity.
  - Shows the UOM abbreviation when present.
- **Reason**
  - Known code-to-label mappings:
    - `damaged` → **Damaged**
    - `wrong_item` → **Wrong Item**
    - `quality_issue` → **Quality Issue**
    - `customer_changed_mind` → **Changed Mind**
    - `other` → **Other**
  - If no mapping exists, displays the raw reason value.
  - Unknown reasons use the “Other” color styling.
- **Disposition**
  - `restock` → **Restock**
  - `quarantine` → **Quarantine**
  - Otherwise displays the raw disposition value.
  - The display styling is green for `restock` and yellow for other values.
- **Total**
  - Shows the line subtotal formatted to two decimal places.

### Payment History section

This section appears only when `credit_note.payments` exists and contains at least one payment.

Above the payment table, the section shows:

- Label: **Payment History**
- **Credit Note:** followed by `credit_note.invoice_number`
- A status badge based on `credit_note.status`:
  - `paid` uses a success color.
  - `partially_paid` uses a warning color.
  - Other statuses use the default color.
  - The displayed text replaces an underscore with a space.
- **Balance:** followed by the absolute value of `credit_note.outstanding_balance`, formatted to two decimal places.

The payment table has four columns:

1. **Date**
   - Localized `payment_date`, or `-`.
2. **Method**
   - A method icon and the payment method text, or `-`.
   - Icon mapping is case-insensitive:
     - `cash` → banknote icon.
     - `card` → credit-card icon.
     - `multiple` → wallet icon.
     - Any other value → credit-card icon.
3. **Reference**
   - `payment_reference`, or `-`.
4. **Amount**
   - `payment_amount`, formatted to two decimal places.

### Remarks and modal action

- If `viewingReturn.remarks` is present, the modal shows a **Remarks** heading and the remarks text.
- The modal footer has a **Close** button. It clears the selected return and closes the detail modal.

## 3.6 Printing a return

When a return is selected, the page also renders a print-content element referenced by `printRef`. The user-facing **Print** action opens a new window and prints that element’s HTML.

The print document includes:

- Browser print title: **“Sales Return — [SR number]”**
- Heading: **SALES RETURN**
- Return number
- Summary fields:
  - **Sales Order**
  - **Customer**
  - **Return Date**
  - **Warehouse**
  - **Received By**
  - **Status**, shown as **COMPLETED**
- A line table with:
  - **Item**
  - **Qty**
  - **Reason**
  - **Disposition**
  - **Total**
- A **Grand Total** row.
- **Remarks**, when present.
- A footer reading **“Printed on [localized print date/time]”**.

The printed item text includes the item name (or the fallback text **“Item”**), variant name when applicable, batch number when present, and serial number when present. Printed quantities use two decimal places and include the UOM abbreviation when available. The print output does not include the modal’s Payment History section or its free-quantity parent text.

The print handler returns without printing if it cannot find the print element or if `window.open` fails. The Print menu action calls `openDetail` and separately schedules `handlePrint` after 500 ms; the code does not wait for the detail fetch to finish before that timer fires.

## 3.7 List-page workflow

1. Open **Sales Returns** from the Sales menu at `/sales/returns`.
2. The page requests the current return list with the current page, a page size of 15, and the debounced search text.
3. Enter text in the search control to search using the placeholder-supported terms **SR #** and **SO #**. After 500 ms, the page resets to page 1 and fetches again.
4. Use pagination when results are present to move between pages.
5. Click a return row or choose **View Details** to open the details modal.
6. Choose **Print** from a row’s action dropdown to invoke the print flow.
7. Choose **Create Return** to follow the code’s `/returns/create` link to the creation flow.

---

# 4. Page: Create Sales Return — `/returns/create`

## 4.1 Page heading and initial state

The page heading is **Create Sales Return**.

Description:

> Process a return from a Sales Order or POS transaction.

The page begins in one of two main states:

- **No transaction selected:** shows a transaction-selection prompt and a **Search Transaction** button.
- **Transaction selected:** shows transaction details and, when returnable lines are present, return-entry controls.

A search modal can be opened from either the initial prompt or the selected-transaction card.

## 4.2 No-transaction-selected screen

When `selectedDocument` is empty, the page shows:

- A search icon.
- Heading: **Select a Transaction**
- Text: **“Search and select an existing Sales Order or POS Sale to initiate a return.”**
- Button: **Search Transaction**

Clicking the button opens the **Select Transaction** modal.

## 4.3 Select Transaction modal

The modal title is **Select Transaction** and its size is set to `2xl`.

### Filter controls

The modal contains these four controls:

1. **Transaction Type**
   - Options:
     - **All Transactions**
     - **Sales Order**
     - **POS Sale**
   - Default: **All Transactions**.
2. **Customer**
   - A `PartyPicker` configured with `partyType="customer"`.
   - The selected party ID and displayed party name are stored separately.
3. **Date Range**
   - Uses `DateRangePicker`.
   - Initial preset: `last_30_days`.
   - Initial date range: from 30 days before the current date through the current date.
4. **Search**
   - Placeholder: **Search number...**
   - Search icon.
   - Searches using the modal search text.

When the modal is open, changes to these filters trigger a search after a **500 ms** delay.

### Transaction results table

The results table has six columns:

1. **Transaction #**
2. **Type**
3. **Customer**
4. **Grand Total**
5. **Date**
6. An unlabeled action column displaying an arrow icon.

For a result:

- **Transaction #**
  - Sales Order number for a Sales Order.
  - POS number for a POS Sale.
- **Type**
  - **Sales Order** or **POS Sale**.
- **Customer**
  - Customer name, or party name, or `-`.
- **Grand Total**
  - Formatted to two decimal places.
- **Date**
  - Localized `created_at` date.
- The row displays a right-arrow icon.

Clicking a result row:

1. Sets the source type to `sales_order` or `pos_sale`.
2. Stores the document ID.
3. Closes the modal.
4. Fetches the selected document and its returnable lines.

### Modal result states and action

- During a search, the table displays a loader and **Searching...**
- When no results are found, it displays:
  - **No transactions found**
  - **Try adjusting your filters**
- The modal footer contains a **Close** button.

### Search requests used by the modal

- The common search parameters are:
  - `search`
  - `page: 1`
  - `per_page: 50`
  - `party_id`, if a customer is selected
  - `date_from`, if the range has a start date
  - `date_to`, if the range has an end date
- For Sales Orders, the request additionally uses status **`completed,partially_shipped`**.
- For POS Sales, the supplied code calls `getPosSales` with the common parameters; it does not add that Sales Order status filter.
- Depending on Transaction Type, the page requests Sales Orders, POS Sales, or both.
- Successful results are tagged internally with their source type, combined, and sorted by `created_at` descending.
- A search error produces the toast **“Failed to search transactions”**.

## 4.4 Selected transaction card

After a document is selected, a card shows:

- A source label: **Sales Order** or **POS Sale**
- The document number:
  - `so_number` for a Sales Order.
  - `pos_number` for a POS Sale.
- **Customer:** customer name, party name, or `-`.
- A **Change Transaction** button, which reopens the transaction-selection modal.

### Sales Order summary fields

For a Sales Order, the card shows:

- **Warehouse** — warehouse name or `-`.
- **Invoice** — invoice number or `-`.
- An invoice-status label if an invoice status exists:
  - `paid` receives green styling.
  - Other statuses receive orange styling.
  - The status text is displayed as supplied.
- **Status** — the order status or `-`.
- **Grand Total** — formatted to two decimal places.

When the fetched Sales Order has a `warehouse_id`, that ID is also used to populate the receiving warehouse state.

### POS Sale summary fields

For a POS Sale, the card shows:

- **Terminal** — terminal name, terminal `name`, terminal code, or `-`, in that order.
- **Cashier** — cashier name or `-`.
- **Invoice** — invoice number or `-`, plus the conditional invoice status label described above.
- **Grand Total** — formatted to two decimal places.

For the receiving warehouse ID, the POS fetch uses the GIN warehouse ID when present; otherwise it uses the terminal warehouse ID when present.

## 4.5 Loading the source document and building returnable lines

When a source document is fetched, the page sets its loading state and clears the current lines first.

### Sales Order source

- Calls `getSalesOrder(Number(id))`.
- On a successful result:
  - Stores the Sales Order as the selected document.
  - Uses the Sales Order warehouse ID when available.
  - Collects lines from all `goods_issue_notes`, flattening their `lines` arrays.
- A source GIN line is included only when:

  `dispatch_quantity - returned_quantity > 0`

- The initial maximum returnable quantity is that net dispatched quantity.

### POS Sale source

- Calls `getPosSale(Number(id))`.
- On a successful result:
  - Stores the POS Sale as the selected document.
  - Sets the warehouse ID from the POS Sale’s GIN if available, otherwise from the terminal if available.
  - Uses the lines from `sale.gin.lines`.
- The same net-quantity condition is applied:

  `dispatch_quantity - returned_quantity > 0`

### Line information and initial values

Each included source line is represented with:

- GIN line ID.
- UOM ID, from the UOM object or the source line’s UOM ID.
- Item name, with additional identifying information where available:
  - Item name, or **“Deleted Item (ID: [item_id])”** if the name is unavailable.
  - Variant name in parentheses when the item has variants and a variant is present.
  - **Deleted** indicator when the item or variant has a `deleted_at` value.
  - **Free** badge when the source line is free quantity.
  - For free lines with parent IDs, a **For:** display built from parent item names and variants, or `#[parent ID]` when a parent item cannot be resolved.
  - Batch number when present.
  - Serial number when present.
- Maximum returnable quantity: net dispatched quantity.
- Initial return quantity: empty.
- UOM abbreviation when available.
- Initial reason: `damaged`.
- Initial disposition: `restock`.
- Batch ID:
  - Sales Order source: uses the source line’s batch ID or an empty value.
  - POS Sale source: initialized as an empty value in the supplied code.
- Per-line remarks: initialized as empty.
- Selected state: false.
- Unit price and unit discount: converted to numbers, defaulting to zero.
- Free-quantity flag and parent line IDs when present.

A line is considered returnable in the UI unless `line.item.is_returnable` is explicitly `false`, and provided the item and variant are not deleted. A line that fails that test is still mapped into the list if its net dispatched quantity is positive, but it is marked non-returnable.

If no returnable-by-quantity lines are found, the page shows a toast:

- **“No returnable items found in this Sales Order.”**, or
- **“No returnable items found in this POS Sale.”**

If the source lookup does not succeed with a result, the page shows:

- **“Sales Order not found”**, or
- **“POS Sale not found”**.

A thrown document-fetch error shows **“Error fetching document”**. The loading state is cleared when the fetch completes.

## 4.6 Return Details section

This section is rendered when a selected document has at least one line.

### Return Date

- Input label: **Return Date**
- Input type: date.
- Initial value: the current date in `YYYY-MM-DD` form.
- The user can change the date.

### Returnable Items table

The table columns are:

1. **Select**
2. **Item**
3. **Net Price**
4. **Max Qty**
5. **Return Qty**
6. **Reason**
7. **Disposition**

For each line:

#### Select checkbox

- Initially unchecked.
- Disabled for lines marked non-returnable.
- When checked:
  - The line becomes selected.
  - If it has no return quantity yet, the return quantity is set to the line’s maximum returnable quantity.
- When unchecked:
  - The line becomes unselected.
  - Its return quantity is cleared.

#### Item

Displays the source line information described above. A non-returnable line also displays:

- **Non-Returnable**, with an alert icon.

#### Net Price

Displays:

`unit_price - unit_discount`

Formatted to two decimal places.

#### Max Qty

Shows the maximum returnable quantity and the UOM abbreviation when available.

#### Return Qty

- Numeric input.
- Placeholder: **0.00**
- `min="0"`, `step="any"`, and `max` set to the line’s maximum returnable quantity.
- Disabled until the line is selected.
- If a typed value is numerically greater than the maximum, the UI replaces it with the maximum.
- The UI does not clamp a negative value in the shown change handler; submission checks the selected line’s quantity.

#### Reason

A select control, disabled until the line is selected. Options:

- **Damaged** (`damaged`)
- **Wrong Item** (`wrong_item`)
- **Quality Issue** (`quality_issue`)
- **Customer Changed Mind** (`customer_changed_mind`)
- **Other** (`other`)

Initial selection: **Damaged**.

#### Disposition

A select control, disabled until the line is selected. Options:

- **Restock to Inventory** (`restock`)
- **Quarantine (Do Not Restock)** (`quarantine`)

Initial selection: **Restock to Inventory**.

### Remarks

Below the line table is an input labeled **Remarks**, with placeholder:

> Any additional notes or instructions...

This page-level Remarks value is included in the submission payload. The code initializes a `remarks` field on each return line, but does not render a per-line remarks input in the supplied JSX.

## 4.7 Refund Settlement section

This section appears only when:

- A selected document has lines, and
- The calculated `refundTotal` is greater than zero.

The displayed refund total is calculated from selected lines with a positive return quantity:

`(unit_price - unit_discount) × return_quantity`

The section displays:

- Heading: **Refund Settlement**
- Description: **“Record a payment to refund the customer immediately”**
- **Total Refund Value**, formatted to two decimal places.
- Checkbox text: **Process immediate refund**
  - Initially checked.
  - When checked, renders a `PaymentSection`.
  - When unchecked, the `PaymentSection` is hidden.

The supplied code passes these props into `PaymentSection`:

- `totalAmount`
- `payments`
- `onPaymentsChange`
- `fetchPaymentModes={getPaymentModes}`
- `fetchBankAccounts={getBankAccountsLookup}`
- `fetchChequeLeaves={searchAvailableChequeLeaves}`

**The implementation of `PaymentSection` is not included in the supplied code. Its internal fields, labels, controls, and conditional rendering cannot be documented from this source.** The validations and payment metadata keys explicitly checked by this page are listed in the validation section below.

## 4.8 Cancel and submission controls

When lines exist and a document is selected, the page renders an action row containing:

- **Cancel** — navigates to `/returns`.
- **Submit Return** — calls the submission handler, shows a loading state while submitting, and is disabled when `lines.length === 0`.

A second action area is rendered unconditionally at the bottom of the page:

- **Cancel** — also navigates to `/returns`.
- **Submit** — calls the same submission handler, shows a loading state while submitting, and is disabled when `lines.length === 0`.

Thus, when a selected document has lines, the supplied JSX renders both the conditional action row and the unconditional bottom action area. When there are no lines, the unconditional bottom controls remain, with Submit disabled because the line count is zero.

## 4.9 Create-return workflow

1. Open the create flow from **Create Return** on the Sales Returns list, or arrive with supported source query parameters.
2. If no document was auto-fetched, click **Search Transaction**.
3. In **Select Transaction**, choose a transaction type, optionally select a customer, set a date range, and enter a search term.
4. Select a returned Sales Order or POS Sale row.
5. Review the displayed source document details and the loaded returnable-item rows.
6. Set **Return Date** if needed.
7. Select each line to return. Selecting a line with an empty quantity defaults its quantity to the line’s maximum returnable quantity.
8. Adjust **Return Qty** as needed; choose a **Reason** and **Disposition** for each selected line.
9. Enter page-level **Remarks** if needed.
10. If the calculated refund total is greater than zero, choose whether to process an immediate refund. If it remains enabled, complete the payment information in the rendered `PaymentSection`.
11. Click **Submit Return** or **Submit**.
12. On success, the page shows a success toast containing the returned SR number when provided and navigates to `/returns`.
13. On failure, the page displays the returned error message or a fallback toast.

---

# 5. API and data flow

## 5.1 List and detail page

The list page uses:

- `getSalesReturns(params)` with:
  - `page`
  - `per_page: 15`
  - `search: debouncedSearch`

On a successful response with a result, it reads:

- Return rows from `result.data`, defaulting to an empty array.
- Total pages from `result.meta.last_page`, then `result.last_page`, then 1.
- Total items from `result.meta.total`, then `result.total`, then 0.

List-fetch exceptions show a toast with the exception message or **“Failed to load returns”**.

The detail view uses:

- `getSalesReturn(sr.id)`

A successful result replaces the selected row data used by the modal and print view.

## 5.2 Transaction search and source-document lookup

The create page uses:

- `getSalesOrders` for Sales Order searches.
- `getPosSales` for POS Sale searches.
- `getSalesOrder(Number(id))` to load a Sales Order and its GIN lines.
- `getPosSale(Number(id))` to load a POS Sale and its GIN lines.

Transaction-search requests are filtered by the modal’s search term, customer, date range, and transaction type. Sales Order searches additionally request statuses `completed,partially_shipped`; the supplied POS search call does not add that status parameter.

## 5.3 Return creation request

The page calls `createSalesReturn(payload)`.

The payload contains:

- `sales_order_id`
  - Numeric document ID for a Sales Order source.
  - `null` for a POS Sale source.
- `pos_sale_id`
  - Numeric document ID for a POS Sale source.
  - `null` for a Sales Order source.
- `warehouse_id`
  - Numeric receiving warehouse ID.
- `return_date`
- `remarks`
  - The entered page-level remarks, or `null`.
- `lines`
  - Only selected lines with a numeric return quantity greater than zero.
  - Each line sends:
    - `sales_order_line_id`, or `null`.
    - `gin_line_id`, or `null`.
    - `uom_id`, or `null`.
    - `batch_id`, converted to a number when present, or `null`.
    - `return_quantity`, converted to a number.
    - `return_reason`
    - `disposition`
    - `is_free_qty`, defaulting to false.
    - `parent_line_ids`, or `null`.
    - Per-line `remarks`, or `null`.
- `is_immediate_refund`
- `payments`
  - The current payment entries when immediate refund is enabled.
  - An empty array when immediate refund is disabled.

On a successful create response:

- Toast: **“Sales Return [SR number] Created successfully”** (the number portion is empty if the response does not provide it).
- Navigation to `/returns`.

On an unsuccessful response:

- Toast uses `res.message`, or **“Failed to create return”**.

On a thrown error:

- Toast uses the exception message, or **“An error occurred”**.

The shown Sales Order and POS line-mapping code assigns a `gin_line_id`, but does not assign a `sales_order_line_id` in the mapped return-line objects. Consequently, the create payload expression for `sales_order_line_id` resolves to `null` for those mapped lines unless another source modifies that property.

---

# 6. UI checks and business rules visible in this source

The supplied material contains no `--- EXTRACTED BACKEND VALIDATIONS ---` content and does not include backend validation code. The following are **frontend checks and behaviors implemented in the supplied React source**, not confirmed backend rules.

## 6.1 Required receiving warehouse

Before submission, if there is no `warehouseId`, the page stops and shows:

> Please provide a Receiving Warehouse ID

The shown form displays a source warehouse summary when available, but the supplied JSX does not render an editable receiving-warehouse input.

## 6.2 At least one valid selected line

The page forms `selectedLines` from lines where:

- `selected` is true, and
- `Number(return_quantity) > 0`

If there are no such lines, submission stops with:

> Select at least one line with a valid return quantity

## 6.3 Returnability check

Before submission, every selected line is checked for `is_returnable`. If any selected line is marked non-returnable, submission stops with:

> One or more selected items are marked as Non-Returnable

The UI also disables the checkbox for a non-returnable line and displays **Non-Returnable** next to it.

## 6.4 Return-quantity check

For each selected line, the handler checks:

- Quantity must be greater than zero.
- Quantity must not exceed `max_returnable`.

If either check fails, submission stops with:

> Return quantity must be between 0.01 and [max_returnable]

The return quantity input also has `min="0"` and `max={line.max_returnable}` attributes, and its change handler clamps values above the maximum to the maximum. The shown handler does not clamp negative values. No maximum quantity beyond the line’s calculated net dispatched quantity is specified in the supplied source.

## 6.5 Immediate-refund payment checks

These checks run only when:

- **Process immediate refund** is enabled, and
- `refundTotal > 0`.

The page then checks:

1. **Payment total equals refund total**
   - Sums payment amounts after converting them to numbers.
   - If the absolute difference from `refundTotal` is greater than `0.01`, submission stops with:
   
     > Total payments must equal the refund total ([formatted refund total])

2. **Every payment has a positive amount**
   - If a payment has no amount or its numeric amount is not greater than zero, submission stops with:
   
     > Please enter a valid amount for all payment methods

3. **Bank transfer requirements**
   - For `mode_code === 'bank_transfer'`, both `metadata.bank_account_id` and `metadata.transfer_reference` are required.
   - Otherwise submission stops with:
   
     > Deposit bank account and transfer reference are required for bank transfers

4. **Cheque requirements**
   - For `mode_code === 'cheque'`, `metadata.cheque_number`, `metadata.cheque_date`, and `metadata.bank_account_id` are required.
   - Otherwise submission stops with:
   
     > Cheque details and deposit bank account are required for cheque payments

5. **Card requirement**
   - For `mode_code === 'card'`, `metadata.bank_account_id` is required.
   - Otherwise submission stops with:
   
     > Deposit bank account is required for card payments

6. **Credit requirements**
   - For `mode_code === 'credit'`, both `metadata.credit_days` and `metadata.due_date` are required.
   - Otherwise submission stops with:
   
     > Credit days and due date are required for credit payments

No other payment modes or payment-field requirements are established by the supplied page code. The internal fields and controls of `PaymentSection` are not supplied.

## 6.6 UI-only line and refund calculations

- A line is included in the returnable-lines list only when dispatch quantity minus returned quantity is greater than zero.
- Its maximum returnable quantity is that difference.
- The line is marked non-returnable if `item.is_returnable` is explicitly false, or if the item or variant has a deletion timestamp.
- The initial line reason is `damaged`.
- The initial line disposition is `restock`.
- Checking a line defaults an empty return quantity to its maximum.
- The displayed net price is unit price minus unit discount.
- The immediate refund total uses net price multiplied by return quantity for selected lines with positive quantities.
- The supplied calculation does not add tax or other charges to that total.
- The reason, disposition, quantity, and payment-total checks described here are frontend behaviors. This source does not establish which corresponding checks, if any, are enforced by the backend.

# 7. Scope limits

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

The supplied returns-page code shows return lines, warehouse names, batches, serial numbers, payment history, and payment-related inputs passed to `PaymentSection`. It does not provide the implementation of those other modules or the internal UI of `PaymentSection`. No additional screens, buttons, fields, backend validation rules, or workflow steps beyond those explicitly described above can be confirmed from the supplied code.

---

## Feature: DELIVERY-NOTES

# Delivery Notes (Goods Issue Notes)

## 1. Global navigation and entry flow

The global Sales menu includes this feature:

- **Sidebar label:** Goods Issue Notes
- **Route:** `/sales/delivery-notes`
- **Sales menu group:** Fulfillment
- **Menu key:** `sales__goods_issue_notes`
- **Permission value in the supplied menu entry:** `null`

The page itself is titled **Delivery Notes** and describes its purpose as **“Goods Issue Notes — dispatch and fulfillment history.”** The supplied menu file confirms that this is a listed Sales page, not a hidden/internal route.

This code contains one page route. It does not define separate sub-pages or additional routes.

## 2. Overview

This page presents a searchable, filterable, paginated list of existing delivery notes (goods issue notes). A user can open a delivery note’s details from its table row or from that row’s **View Details** action. The detail modal can display dispatch information, dispatched line items, remarks, and—when present—associated invoice and payment information.

The page code contains no delivery-note creation or editing form.

**CRITICAL NOTE**: This is a view-only page. Users cannot manually create a delivery-notes here.

The code also does not define controls to save, edit, delete, complete, or otherwise change a delivery note.

## 3. Page layout and UI elements

### 3.1 Page heading and description

The page heading is:

- **Delivery Notes**

The supporting description is:

- **Goods Issue Notes — dispatch and fulfillment history.**

A `RecordCount` component is shown when the list is not loading. The page renders it in the heading area and also in the adjacent controls area. Both instances receive the same `totalItems` value.

### 3.2 Search controls

The page includes search controls for delivery notes:

- Search label on the mobile options component: **Search Delivery Notes**
- Search placeholder: **Search by GIN #, SO #...**
- Desktop search popover placeholder: **Search by GIN #, SO #...**

Both controls use the same `searchTerm` state. Changing the search text updates that state. The page waits 500 milliseconds after a search change before copying the value to `debouncedSearch` and resetting the page number to 1. The debounced value is used in the list request.

### 3.3 Filters control

A **Filters** control is available in both the mobile options dropdown and the main page controls:

- In the mobile options dropdown, **Filters** is a `DropdownItem`.
- In the main controls area, **Filters** is a button with a filter icon.
- Either control toggles the same `showFilters` state.
- The main button’s styling changes when the filter panel is open or when active filters exist.
- When one or more active filters exist, the main button also displays a dot indicator.

For this page, “active filters” means at least one of the following has a value:

- Date From
- Date To
- Customer (`partyId`)
- Sales Order (`salesOrderId`)

Search text is not included in the `hasActiveFilters` calculation.

### 3.4 Expanded filter panel

The filter panel is conditionally rendered when `showFilters` is true.

#### Clear All

When at least one active filter exists, the panel displays a **Clear All** button with an X icon. Clicking it clears:

- Date From
- Date To
- Customer ID
- Customer display name
- Sales Order ID
- Sales Order selected object
- Search text

It also sets the current page to 1.

Although the button is shown based on the date, customer, and sales-order filter state, its handler also clears the search text.

#### Date From

- Label: **Date From**
- Input type: `date`
- Icon: calendar
- Changing the value updates `dateFrom` and resets the page to 1.

#### Date To

- Label: **Date To**
- Input type: `date`
- Icon: calendar
- Changing the value updates `dateTo` and resets the page to 1.

The supplied code does not define additional date-range validation.

#### Customer

A `PartyPicker` is rendered with these supplied props:

- Label: **Customer**
- `partyType`: `customer`
- Its selected value comes from `partyId`.
- Its display value comes from `partyName`.
- On change, the page stores the selected party’s `id` or `null`, stores its `name` or an empty string, and resets the page to 1.

The implementation of `PartyPicker` is not included in the supplied code, so its internal fields, search behavior, or options cannot be specified from this source.

#### Sales Order

An `AsyncSearchableSelect` is rendered with these configured props:

- Label: **Sales Order**
- Placeholder: **Select Sales Order...**
- Option label field: `so_number`
- Option value field: `id`
- `allowClear`: enabled
- Default selected object: `salesOrderObj`

Its option loader calls `getSalesOrders({ search, page })` and returns `res.result?.data || []`.

When a selection changes:

- The selected value is stored as `salesOrderId`, or `null` if no value is selected.
- The selected option object is stored as `salesOrderObj`, or `null`.
- The page number is reset to 1.

### 3.5 Delivery-notes table

The table has seven columns:

1. **GIN #**
2. **Sales / POS**
3. **Customer**
4. **Warehouse**
5. **Dispatch Date**
6. **Status**
7. **Actions**

#### Loading state

While the list request is loading, the table body renders `TLoader` with 7 columns.

#### Empty state

When loading has finished and the list is empty, the table displays an `EmptyState` message:

- **No delivery notes match your filters.** when `hasActiveFilters` is true or `searchTerm` is non-empty.
- **No delivery notes found.** otherwise.

The empty-state check uses the immediate `searchTerm`, not only the debounced search value.

#### GIN # column

Each row displays:

- A package icon.
- The delivery note’s `gin_number`.

The row’s GIN cell is labelled **GIN #** for the table/mobile cell presentation.

#### Sales / POS column

The cell displays the first available value in this order:

1. The related sales order’s `so_number`, if present.
2. Otherwise, the related POS sale’s `pos_number`, if present.
3. Otherwise, a dash (`-`).

#### Customer column

The cell displays the first available customer name in this order:

1. `g.party.name`
2. `g.party.full_name`
3. `g.party.first_name`
4. `g.sales_order.customer.name`
5. `g.sales_order.customer.full_name`
6. `g.sales_order.customer.first_name`
7. A dash (`-`) if none is available

#### Warehouse column

The cell displays `g.warehouse.name`, or a dash (`-`) if there is no warehouse name.

#### Dispatch Date column

The cell displays `g.dispatch_date` formatted with `toLocaleDateString()`, or a dash (`-`) if there is no dispatch date.

#### Status column

The status badge displays the record’s `status` value.

Its color is chosen as follows:

- `success` when `g.status === "completed"`
- `warning` for every other status value

The code does not enumerate the possible status values.

#### Actions column

Each row has a dropdown triggered by a button displaying a vertical-more icon. The actions area stops click propagation so using the dropdown does not also trigger the row’s click handler.

The dropdown contains one action:

- **View Details**, with an eye icon

Selecting it opens the detail modal for that delivery note.

### 3.6 Pagination

Pagination appears only when:

- The list is not loading, and
- At least one delivery note is present on the current page.

It is configured with:

- Current page: `page`
- Total items: `totalItems`
- Items per page: `15`
- Page-change handler: updates `page`

## 4. Delivery Note Details modal

### 4.1 Opening and closing

The modal:

- Has the title **Delivery Note Details**.
- Uses size `lg`.
- Opens when `viewingGin` is non-null.
- Closes through its `onClose` handler, which sets `viewingGin` to `null`.

A user can open it by clicking a table row or selecting **View Details** from the row’s dropdown.

When opened, the page first assigns the clicked list row to `viewingGin`, sets the detail-loading state, and requests the full record. If that request succeeds with a result, the modal content is replaced with the returned result.

### 4.2 Delivery-note identity and related sale

The modal header displays:

- The delivery note’s `gin_number`.
- A related transaction reference:
  - **SO: {sales order number}** when `sales_order.so_number` exists.
  - Otherwise, **POS: {POS number}** when `pos_sale.pos_number` exists.
  - Otherwise, **SO: -**.
- If a customer name is available, a bullet separator followed by that name.

The customer name uses the same fallback order as the table: party name, full name, first name, then the sales order customer’s name, full name, or first name.

A status badge displays `viewingGin.status`. In the modal, the badge color is always configured as `success`; unlike the table badge, this modal badge does not condition its color on the status value.

### 4.3 Dispatch metadata

The modal displays four metadata fields:

- **Warehouse** — `viewingGin.warehouse.name`, or `-`
- **Dispatch Date** — localized dispatch date, or `-`
- **Dispatched By** — `viewingGin.dispatched_by.name`, or `-`
- **Created** — localized `viewingGin.created_at` date, or `-`

### 4.4 Detail-loading state

While `isDetailLoading` is true, the line-items section is replaced with a loading presentation containing a styled placeholder element.

The identity, status, and metadata sections are rendered from the current `viewingGin` value. Because the clicked list row is assigned before the detail request completes, those sections can initially show data from the list row while the detail request is in progress.

If the detail request fails, the catch block does not show an error message. The existing modal record remains, and the loading state is cleared in `finally`.

### 4.5 Dispatched Items section

After detail loading finishes:

- If `viewingGin.lines` contains one or more lines, the modal displays a section titled **Dispatched Items**.
- If there are no lines, it displays **No line items found.**

The dispatched-items table has these columns:

1. **Item**
2. **Dispatched Qty**
3. **Returned**
4. **Price**
5. **Disc.**
6. **Subtotal**

#### Item cell

For each line, the item cell can display:

- The item name from `l.item.name`.
- If there is no item object, **Deleted Item (ID: {item_id})**.
- If the item has variants and the line has a variant, the variant name in parentheses.
- A **Free** badge when `l.is_free_qty` is true.
- If the line is free and `parent_line_ids` contains entries, a **For:** line listing the related parent items:
  - For each parent ID, the code searches `viewingGin.sales_order.lines` for a matching line.
  - When that parent line has an item, it displays the item name and, when available, its variant name in parentheses.
  - When a matching item cannot be found, it displays `#{parent ID}`.
  - Multiple entries are joined with commas.
- If a batch exists, **Batch: {batch_number}**.
- If a serial number exists, **S/N: {serial_number}**.

#### Dispatched Qty

Displays `dispatch_quantity` converted to a number, defaulting to `0` when falsey. If a UOM abbreviation exists, it is displayed after the quantity.

#### Returned

If `returned_quantity` is truthy and converts to a number greater than zero, the cell displays that quantity and, when available, the UOM abbreviation. Otherwise it displays `-`.

#### Price, discount, and subtotal

- **Price** displays `unit_price`.
- **Disc.** displays `unit_discount`.
- **Subtotal** displays the line’s `sub_total`.

These numeric values are formatted with two decimal places and locale-aware number formatting. The subtotal helper converts `line.sub_total || 0` to a number.

### 4.6 Remarks

If `viewingGin.remarks` is truthy, the modal displays:

- The label **Remarks**
- The remarks text

No remarks section is rendered when the value is absent or falsey.

### 4.7 Invoice Details section

If `viewingGin.invoice` exists, the modal additionally displays an **Invoice Details** section containing:

- The invoice number (`invoice_number`)
- An invoice status badge
- **Amount Settled**
- **Amount Due**

The status badge displays `invoice.status`, or **UNPAID** when the status is falsey. Its color is selected as follows:

- `success` when the invoice status is `paid`
- `warning` when it is `partial`
- `danger` for other values

The amounts are formatted to two decimal places using the same formatter as the line-item numbers.

### 4.8 Payment History

Within the invoice section, payment history is displayed only when `invoice.payments` exists and has at least one entry.

The payment table has these columns:

1. **Date**
2. **Method**
3. **Reference**
4. **Amount**

For each payment:

- **Date:** localized `payment_date`, or `-`
- **Method:** `payment_method`, or `-`
- **Reference:** `payment_reference`, or `-`
- **Amount:** `payment_amount` formatted to two decimal places

## 5. Step-by-step user workflows

### 5.1 Open the page

1. Navigate to **Sales → Goods Issue Notes**, listed under the **Fulfillment** group.
2. The page displays the **Delivery Notes** heading and the fulfillment-history description.
3. The page requests the first page of records with a page size of 15.
4. While the request is in progress, the table displays its loading state.
5. When the request finishes, the table displays the returned records, or the relevant empty-state message if none are returned.

### 5.2 Search delivery notes

1. Enter text in the search control with placeholder **Search by GIN #, SO #...**.
2. The entered value is held in the page’s search state.
3. After 500 milliseconds without a subsequent search change, the value is applied as the debounced search and the page is reset to page 1.
4. The list request includes the search value when the debounced value is non-empty.
5. The table updates to show the returned results or the applicable empty state.

### 5.3 Filter by date, customer, or sales order

1. Select **Filters** in the page controls or in the mobile options dropdown.
2. The filter panel opens.
3. Set **Date From**, **Date To**, select a **Customer**, and/or select a **Sales Order**.
4. Each filter change resets the current page to 1.
5. The list request includes the corresponding non-empty filter parameters.
6. The main **Filters** button indicates active filters when any date, customer, or sales-order filter is set.

### 5.4 Clear filters

1. Open the filter panel.
2. When date, customer, or sales-order filters are active, select **Clear All**.
3. The page clears the date fields, customer selection, sales-order selection, and search text.
4. The page resets to page 1 and reloads the list using the cleared filter state.

### 5.5 View a delivery note

1. Click a delivery-note row, or open its actions dropdown and select **View Details**.
2. The modal opens with the row’s current data.
3. The page requests the delivery note’s detailed record by its `id`.
4. While that request is in progress, the line-item section shows its loading presentation.
5. On a successful response with a result, the modal displays the returned record’s details.
6. Close the modal through its close behavior to clear the selected record.

### 5.6 Move between result pages

1. When records are present and the list is not loading, use the pagination control.
2. The selected page updates the page state.
3. The page fetches the records for that page, using the same current search and filter state.

## 6. API and data flow

The page calls the following API functions from the supplied code:

### `getGoodsIssueNotes(params)`

Used to load the list. The request always includes:

- `page`
- `per_page: 15`

It conditionally includes:

- `search` when `debouncedSearch` is non-empty
- `date_from` when `dateFrom` is non-empty
- `date_to` when `dateTo` is non-empty
- `party_id` when `partyId` is truthy
- `sales_order_id` when `salesOrderId` is truthy

When the response has both `is_success` and `result`:

- Rows are taken from `res.result.data`, defaulting to an empty array.
- The total count comes from `res.result.meta?.total`, then `res.result.total`, then `0`.

If the list request throws, the page shows a toast using the thrown error’s message or **Failed to load**. The loading state is cleared in `finally`.

### `getGoodsIssueNote(gin.id)`

Used to load one delivery note’s details after a row is opened.

- The clicked row is immediately placed in modal state.
- The request uses the row’s `id`.
- If `res.is_success` and `res.result` are present, the modal record is replaced with that result.
- A thrown error is silently caught; the code does not display a toast or other error message for this request.
- The detail-loading state is cleared in `finally`.

### `getSalesOrders({ search, page })`

Used by the Sales Order filter’s asynchronous option loader.

- The loader passes its supplied `search` and `page` values to the API function.
- It returns `res.result?.data || []` as the options.
- The select uses `so_number` as the option label and `id` as the value.

## 7. Backend validations and business rules

No **EXTRACTED BACKEND VALIDATIONS** content or backend validation implementation was supplied. Therefore, this source does not establish any backend validation rules, required fields, permissible status transitions, date constraints, quantity limits, or other server-side business rules.

The following are behaviors explicitly visible in the supplied UI code, not claims about backend validation:

- The list request uses a page size of 15.
- Search is debounced by 500 milliseconds.
- Changing search or a filter resets the page to 1.
- The list status badge is styled as success for `completed` and warning for other statuses.
- The modal’s delivery-note status badge is configured with the success color regardless of the status value.
- The UI displays dashes or fallback text for several absent values, as detailed above.
- The supplied page code contains no editable delivery-note form or create/save action.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---

## Feature: ORDERS

# Sales Orders — UI and Behavior Guide

## 1. Global navigation and entry flow

- The global Sales menu includes **Sales Orders** at **`/sales/orders`**, under the **Orders** group. This is a listed Sidebar page.
- The page component renders `SalesOrderList`.
- The page also contains an action that navigates to **`/returns/create?source_type=sales_order&document_id=<order ID>&auto_fetch=true`** when the user processes a return. That route is not listed in the provided global menu. Based on the supplied menu information, treat it as a **hidden/internal route**, not as a Sidebar destination. The listed Sidebar destination for returns is **Sales Returns** at **`/sales/returns`**.
- The code does not define additional Sales Orders sub-pages. Creating and editing an order replace the list with an in-page transaction screen; viewing and fulfillment open modals.

## 2. Overview

The page lets users list, search, filter, inspect, create, edit, confirm, cancel, delete, and fulfill sales orders. Its list displays an order’s number, customer, date, source, grand total, status, and available actions.

The implementation distinguishes these order statuses:

| Status value | List badge label | Detail badge label |
|---|---|---|
| `draft` | Draft | Draft |
| `confirmed` | Confirmed | Confirmed |
| `partially_shipped` | Partial | Partially Shipped |
| `completed` | Completed | Completed |
| `cancelled` | Cancelled | Cancelled |

The source labels shown in the list are **Manual** and **POS** for those matching source values. Other source values fall back to **Quotation**. In the detail view, source values are explicitly displayed as **POS**, **Quotation**, or **Manual**.

**This is not a view-only page.** The code includes a **New Order** action and a transaction-screen submission flow for creating orders. It also supports editing draft orders.

## 3. Page states and conditional rendering

The component can render several distinct states or screens:

1. **Orders list** — the default page.
2. **New Sales Order screen** — opened by either New Order action.
3. **Edit Sales Order screen** — opened from a draft order’s actions or details.
4. **Sales Order Details modal** — opened by clicking a row or choosing View Details.
5. **Fulfillment modal** — opened for a confirmed or partially shipped order.
6. **Insufficient Stock modal** — shown when confirming an order returns the `INSUFFICIENT_STOCK` system code.
7. **Product transaction sub-modals** — the shared transaction screen can render batch, serial, and free-quantity parent-selection components. Their implementations are not included in the supplied source; their exact inner controls cannot be established here.
8. **Serial Number Selection modal** — used by the fulfillment form for serial-tracked items, with its implementation included in the supplied source.

The component also has loading states for the order list, order details/edit/fulfillment fetches, and transaction data. Which transaction-screen fields and panels are visible depends on `TRANSACTION_PRESETS.sales`; the preset definition was not supplied. Where visibility depends on that preset, this guide identifies the condition rather than assuming its value.

## 4. Orders list

### 4.1 Heading and top-level controls

The list page shows:

- Heading: **Sales Orders**
- A record count, rendered when the list is not loading.
- Description: **Manage sales orders and track fulfillment status.**
- Mobile options using `TableMobileOptions`:
  - Search label: **Search Orders**
  - Search placeholder: **Search by SO #, customer...**
  - Search value bound to the page’s search input.
  - A **New Order** dropdown item with a plus icon.
- A desktop control row containing:
  - Another record count, shown when not loading.
  - Status filter buttons: **All**, **Draft**, **Confirmed**, **Partial**, **Completed**, and **Cancelled**.
  - A desktop search popover with placeholder **Search by SO #, customer...**
  - A **New Order** button with a plus icon.

Selecting a status filter sets the filter and returns the list to page 1. **All** uses an empty status value.

### 4.2 Search behavior

- Search text is stored immediately as the user types.
- The API search value is debounced by **500 ms**.
- After the debounce, the debounced search is updated and pagination returns to page 1.
- The list request includes `search`, even when the search is empty.
- The backend list service searches order numbers and customer first and last names. The supplied service code does not search item names.

### 4.3 Orders table

The table has these seven columns:

1. **SO #** — displays `so_number`.
2. **Customer** — displays the customer name, or `-` if missing.
3. **Date** — displays the order date through `DateLabel`, or `-` if absent.
4. **Source** — displays the source label:
   - `pos` → **POS**
   - `manual` → **Manual**
   - Other values → **Quotation**
5. **Grand Total** — formatted with two decimal places.
6. **Status** — a colored badge using the status mapping above. Unknown status values fall back to the Draft mapping.
7. **Actions** — a vertical-ellipsis dropdown.

Clicking a row opens its details. Clicking within the Actions cell stops the row click from also opening details.

### 4.4 Loading, empty, and pagination states

- While loading, the table renders a loader spanning seven columns.
- When loading is complete and there are no orders, the table shows **No sales orders found.**
- When loading is complete and there is at least one order, pagination is shown.
- The list requests **15 orders per page**. Pagination receives the current page, total item count, and page size 15.
- A record count appears above the list when it is not loading.

## 5. Actions available by order status

The actions dropdown contains **View Details** for every listed order. Other actions are status-dependent:

| Action | Displayed when | Effect |
|---|---|---|
| **Edit Order** | Draft | Fetches the full order and opens the edit transaction screen. |
| **Confirm** | Draft | Shows a confirmation prompt, then calls the confirm action. |
| **Fulfill / Dispatch** | Confirmed or partially shipped | Fetches the full order and opens the fulfillment modal. |
| **Process Return** | Completed or partially shipped | Navigates to the internal return-creation URL with the order ID in the query string. |
| **Cancel** | Confirmed | Shows a cancellation prompt, then calls the cancel action. |
| **Delete** | Draft | Shows a deletion prompt, then calls the delete action. |

The action prompts contain these exact texts:

- Confirm:
  - Title: **Confirm Order?**
  - Body: **This will lock the order for fulfillment.**
- Cancel:
  - Title: **Cancel Order?**
  - Body: **This action cannot be undone.**
- Delete:
  - Title: **Delete Order?**
  - Body: **This will permanently delete the order.**

The same draft-order delete and confirm actions, and the confirmed-order cancel action, are also available from the details modal.

## 6. Creating and editing an order

### 6.1 Opening the transaction screen

The **New Order** button and mobile **New Order** item set the page to the transaction screen. The screen shows:

- A back-arrow button. Clicking it returns to the list and clears the editing order.
- A heading:
  - New flow: **New Sales Order**
  - Edit flow: **Edit Sales Order `<order number>`**
- Helper text: **Search products, set quantities and pricing**
- A `ProductTransactionScreen` configured from `TRANSACTION_PRESETS.sales`, with these explicit overrides:
  - `submitLabel` is **Update Sales Order** when editing; otherwise it uses the preset’s `submitLabel`.
  - `enableSalesUnit` comes from the loaded Sales settings.
  - `disableTrackingSelection` is `true`.
  - `disablePartySelection` is `true` when editing and `false` for a new order.
- On edit, the full order is fetched first and passed as `initialData`.

The exact new-order submit label and the values of other preset-driven configuration flags cannot be confirmed because the preset definition is not included in the supplied code.

### 6.2 Shared product transaction screen

The following fields and behaviors come from the supplied `ProductTransactionScreen`, `ProductSelectionPanel`, and `MetadataPanel` code. Their visibility is conditional on the Sales preset unless specifically noted.

#### Product search and selection

If `disableItemSelection` is false, the product panel provides a search input:

- Placeholder is **Select a warehouse first to search items...** when `requireWarehouseFirst` is true and no warehouse is selected.
- Otherwise, placeholder is **Search by name, SKU, or scan barcode...**
- Search results are requested after **250 ms**.
- The request includes the search text, a limit of 20, and the transaction type. It includes a warehouse ID when one is selected. Sales-type searches also request application of sales prices and include the transaction type and selected party when available.
- Search results can show item image or a package icon, item name, SKU, variant count, price when prices are enabled, and available stock when stock display is enabled.
- Variant-bearing items can be expanded to show variants. Variant rows can display variant name, SKU, price, and available stock, subject to the configuration flags.
- The results panel can display **No items found for “`<search>`”** when a search has no results.
- Arrow Up and Arrow Down move the highlighted result; Enter selects or expands the highlighted item; Escape closes the results.
- An auto-add toggle controls whether exact matches are automatically added. Its hint reads: **Automatically adds an item to the list when a barcode is scanned or an exact match is found.**
- If an `onAddNewItem` callback is supplied, a plus control with the title **Create new item** is displayed. The Sales Orders page does not supply that callback in the shown `ProductTransactionScreen` invocation, so this source does not establish that this control appears on this page.

When there are no transaction lines, the item area shows:

- **No items added**
- **Search for products above to add them**

#### Transaction line table

When lines exist, the product table can contain these columns, controlled by configuration:

- **Item**
- **Qty**
- **Unit**, when purchase or sales units are enabled
- **Rate**, when prices are shown
- **Disc.**, when prices are shown and the transaction type is sales, quotation, or POS
- **Total**, when prices are shown
- An unlabeled action column containing a remove-item control

For each item line, the item cell can show the item image or package icon, item name, SKU, variant information, and a **Free** marker for a free-quantity line. For variant-bearing items, the panel either allows an “Any Variant” line or provides a variant selector, depending on configuration.

Quantity is a numeric input with `min={0.001}` and `step="any"` in the UI. The component’s update handler clamps an entered quantity to a minimum of zero. The supplied backend request imposes a different, explicit minimum of `0.0001`; see backend rules below.

When the Unit column is enabled, the user can choose among the item’s unit-of-measure group entries. That selector is disabled for serial-tracked lines and while a Sales-module batch line has no selected batch.

When prices are shown, Rate is an editable text input limited by its input handler to digits and at most two decimal places. It is disabled when `allowEditPrice` is false, for a free-quantity line, or while a Sales-module batch line has no batch selected.

The line total is formatted to two decimal places. A trash icon removes the line.

#### Discount control and every disabling condition

The discount column is rendered only when prices are shown and the transaction type is sales, quotation, or POS. Its control has:

- A dropdown with **Amt** and **%** options.
- A numeric input with placeholder **0.00**, `min={0}`, and `step="any"`.

The discount control is disabled if **any** of the following conditions is true:

1. `config.allowEditPrice` is false.
2. The line is marked as free quantity.
3. The line is a Sales-module type (sales, quotation, or POS) and `line.item.is_discountable` is false.
4. The unit price is zero.
5. The line is a Sales-module type, is batch-tracked, and has no selected batch (`isBatchPending`).

The UI’s amount-mode handler limits the per-unit discount amount to a value between zero and the unit price, then derives the percentage. Percentage mode clamps the percentage to the UI range 0–100. These are UI behaviors; they are not additional backend rules in the supplied order request.

#### Free quantity and parent association

For a zero-priced line of a supported transaction type, the line can show a **Free Quantity** checkbox. For Sales Orders, the component’s condition includes sales transactions.

- The checkbox is disabled if the line is linked to a purchase-order, sales-order, or sales-quotation line.
- When checked, the line’s unit price, discount, and total are set to zero.
- A free line can show a parent-line selector labeled **Select Parent Line...** or a selected parent description.
- The supplied `ParentLineSelectionModal` implementation is not included, so its internal fields and exact modal text cannot be documented from this code.
- The shared transaction code removes a line’s UID from other lines’ parent associations when that line is removed or changed from free quantity.

#### Batch and serial behavior on the Sales Orders screen

The Sales Orders page explicitly sets `disableTrackingSelection: true`. This affects the shared product-selection behavior: selecting an item does not open the shared initial batch or serial selector through the normal tracked-item selection branch.

Batch-tracked Sales lines nevertheless have explicit batch handling in the line table because the Sales panel has a separate Sales/quotation/POS batch branch:

- A batch-tracked line shows an **AsyncSearchableSelect** with placeholder **Select Batch...**
- Its options are loaded from the item-batch lookup, with variant and warehouse filters when available.
- The displayed option includes the batch number and, when a warehouse is selected, available stock.
- Selecting a batch updates the line’s batch and rate from its selling price.
- A warning icon is shown when no batch is selected.
- A batch line without a selected batch is considered pending for the Rate input and discount-disable logic.

Serial-selection controls in `ProductSelectionPanel` are conditioned on tracking-selection configuration in the supplied code. Because the Sales Orders page sets `disableTrackingSelection` to true, the normal serial-selection prompt in that panel is not established as visible here. The fulfillment form has its own separate serial-selection flow, described later.

The shared source includes `BatchSelectionModal`, `SerialSelectionModal`, and parent-line selection components, but their implementation source is not included. Do not infer their inner fields or text from their usage alone.

#### Transaction totals

The shared transaction screen computes:

- Subtotal from unit price × quantity.
- Discount total from line discount amounts.
- Grand total as subtotal minus discount total.

The product panel also shows a line count, total units (adjusted using the selected unit conversion factor), and a formatted total when prices are enabled. Some total displays are specifically conditional on transaction type or configuration; for example, the transaction screen’s prominent **Amount to Pay** block is rendered only for POS, so it is not established as a Sales Orders display.

#### Metadata panel fields, conditional on Sales preset

The `MetadataPanel` source provides these controls when its configuration and callbacks enable them:

- **Party/customer picker** when `showParty !== false`. The party type and displayed label come from configuration. Party selection is disabled while editing this Sales Order because the page sets `disablePartySelection` for edits.
- **Warehouse** picker when `showWarehouse` is enabled. It is required in the component, unless configuration changes the display behavior; the Sales Orders page does not explicitly override warehouse selection.
- **Date** field when a date-change callback is supplied. The transaction screen supplies this callback and initializes the date to today.
- Expected-delivery date when `showExpectedDeliveryDate` is enabled. Its label comes from configuration or defaults to **Expected Delivery**.
- **Notes** textarea when `showNotes` is enabled. Its placeholder is **Add transaction notes...**
- Currency picker and, for a non-base currency, an **Exchange Rate** input only when currency is enabled.
- Supplier reference only when `showSupplierReference` is enabled.
- Other Expenses control only when `showOtherExpenses` is enabled.
- Payment section only when `showPayment` is enabled.
- A submit button whose text is `config.submitLabel`. It is disabled when there are no line items and shows loading while submitting.

The Sales preset’s values for these visibility flags are not present in the supplied code, so the conditional controls above should not be mistaken for a definitive list of fields visible in this particular runtime configuration.

#### Price-list behavior supplied by the shared component

For sales-type transactions, the shared component checks whether active price lists exist. It can evaluate price rules for a selected party and variant lines. If the party changes and the evaluation detects actual price changes, it opens a modal:

- Title: **Price List Update**
- Confirm-style body: **A few items have price changes based on the price list. Do you want to apply them?**
- Force-style body: **Prices need to be changed based on the party selection.**
- In the confirm-style case, buttons are **No** and **Yes**.
- In the force-style case, the action button is **OK**.
- Applying the update recalculates applicable line prices and shows the toast **Prices updated based on party selection**.

Whether a particular run reaches this modal depends on active price-list data, the selected party, and the returned price evaluation; the code does not guarantee that it appears for every order.

### 6.3 Submitting a new or edited order

The transaction screen’s submit handler does not submit when there are no lines. It builds a transaction payload, then `handleTransactionSubmit` in the Sales Orders page maps it to the Sales Order API payload:

- `party_id` from the transaction payload.
- `warehouse_id` from the transaction payload.
- `order_date` from `transaction_date`, or today if absent.
- `remarks` from transaction `notes`.
- Lines containing:
  - `item_id`
  - `variant_id` or `null`
  - `uom_id` or `null`
  - `batch_id` or `null`
  - `quantity`
  - `unit_price`
  - `unit_discount`, defaulted to zero
  - `tax_rate` set to zero
  - `remarks` set to `null`
  - `is_free_qty`
  - `serial_numbers` or `null`
  - `parent_line_uids`
  - `uid`

Notably, although the shared transaction screen can collect an expected-delivery date, this Sales Orders payload mapping does **not** include `expected_delivery` or `expected_delivery_date`. The provided page code therefore does not pass that value to the Sales Order create/update call.

- For a new order, the page calls `createSalesOrder`.
- For an edit, it calls `updateSalesOrder` with the current order ID.
- On success, the page shows a toast of the form **Sales Order `<SO number>` created** or **Sales Order `<SO number>` updated**, closes the transaction screen, clears edit state, and refreshes the list.
- On an unsuccessful response, it shows the response message or a create/update failure message. The handler also throws after showing the error, and its catch can show a further error toast.
- On thrown errors, it shows the error message or a general create/update error message.

### 6.4 Editing an existing draft

Editing is available only from the UI for draft orders. The page first requests the full order.

It maps order lines into transaction-screen initial data, including the item and variant, unit of measure, quantity, unit price, free-quantity state, serial numbers, and batch data. It also creates UIDs for lines and translates returned parent-line IDs to those UIDs.

The edit screen:

- Shows **Edit Sales Order `<SO number>`**.
- Passes the existing order as `initialData`.
- Disables party selection.
- Uses the submit label **Update Sales Order**.
- Uses the same transaction submission handler, which calls `updateSalesOrder`.

The page reports **Failed to load order details** if the detail fetch returns an unsuccessful response. Exceptions are shown as their message or **An error occurred while loading order**.

## 7. Sales Order Details modal

Clicking a list row or choosing **View Details** fetches the full order and opens an `EntityDetailModal` titled **Sales Order Details**. The modal content is `SalesOrderDetail`. While fetching, a shared loading flag is set; the detail component itself does not render a separate loading message in the supplied code.

### 7.1 Header and order information

The detail view shows:

- Sales order number.
- Customer name, or **Unknown Customer** if absent.
- Status badge, with the detail-specific status labels from the table above.

It then displays:

- **Order Date** — localized date or `-`.
- **Expected Delivery** — localized date or `-`.
- **Warehouse** — warehouse name or `-`.
- **Source** — POS, Quotation, or Manual.

### 7.2 Line Items table

The line-items section appears only when the order has at least one line. Its columns are:

1. **Item**
2. **Qty**
3. **Fulfilled**
4. **Returned**
5. **Price**
6. **Disc.**
7. **Subtotal**

The Item cell can show:

- Item name, or **Deleted Item (ID: `<item ID>`)**.
- Variant name in parentheses when the item has variants and a variant is present.
- **Free** badge for a free-quantity line.
- For a free line with parent IDs, **For:** followed by resolved parent item names or `#<ID>` fallbacks.
- **Batch:** followed by the distinct batches associated with the order line and its goods issue notes.
- **SN:** followed by distinct serial numbers from the order line and its goods issue notes.

Other displayed line values include:

- Quantity and unit abbreviation when available.
- Fulfilled quantity and unit abbreviation. The fulfilled value is styled green when it meets or exceeds ordered quantity, amber when it is greater than zero but below ordered quantity, and gray when it is zero.
- Returned quantity and unit abbreviation when positive; otherwise `-`.
- Price, discount, and subtotal formatted to two decimal places. Discount displays `unit_discount` or falls back to `discount`.

### 7.3 Totals, remarks, and footer actions

- **Grand Total** is always rendered in the detail content and formatted to two decimal places.
- **Remarks** appears only when the order has remarks.
- The footer always has **Close**.
- For a draft order, the footer can also show:
  - **Delete**, with the delete confirmation prompt.
  - **Edit Order**.
  - **Confirm Order**, with the confirm prompt.
- For a confirmed order, it can show **Cancel**, with the cancel prompt.
- For a confirmed or partially shipped order, it can show **Fulfill / Dispatch**.

On successful detail actions, the relevant handler runs and the details modal closes according to the page’s callback. The list refresh is performed by the corresponding action handler when it succeeds.

## 8. Fulfill / Dispatch modal

Selecting **Fulfill / Dispatch** fetches the full order and opens a modal titled **Fulfill — `<SO number>`**, size `xl`. The fulfillment form contains only lines with fulfilled quantity below ordered quantity.

### 8.1 Header fields

- **Warehouse** picker:
  - Marked required.
  - Disabled in this form.
  - Initialized from the order’s warehouse ID and name.
- **Dispatch Date**:
  - Date input.
  - Defaults to today.
  - Editable.

Although the warehouse picker is disabled, the submit handler still checks that a warehouse ID exists. If it is absent, it shows **Please select a warehouse** and does not submit.

### 8.2 “Lines to Fulfill” table

The section heading is **Lines to Fulfill**. Columns are:

1. **Item Details**
2. **Ordered**
3. **Issued**
4. **Issue Qty**
5. **Tracking Selection**
6. **Remarks**

Each line can display:

- Item name, or **Deleted Item (ID: `<item ID>`)**.
- Variant name when applicable.
- **Free Item** for a free-quantity line.
- **For:** followed by parent item names when available.
- The order’s preselected batch number, if present.
- Ordered quantity and unit abbreviation.
- Previously fulfilled quantity and unit abbreviation.
- Editable Issue Qty input with `step="0.01"`, initialized to the remaining quantity.
- Optional per-line **Remarks** input with placeholder **Optional**.

Tracking behavior depends on the item:

- **Batch-tracked line with no preselected batch:** a batch dropdown appears. It is disabled if there is no warehouse or while batches are loading. Its empty option reads:
  - **Select warehouse**
  - **Loading batches...**
  - **Select batch...**
  depending on state.
  Available options show a batch number (or `Batch #<ID>`) and show available quantity when that value is truthy.
- **Batch-tracked line with a preselected batch:** shows **Locked to Batch in SO**. The batch selector is not offered.
- **Serial-tracked line:** a button opens serial selection:
  - **Select Serials** when none are selected.
  - **`<count>` Serial(s) Selected** when serials have been selected.
  - A mismatch message appears if the selected count differs from Issue Qty: **Mismatch: `<selected>` selected vs `<required>` required**.
  - If there is no warehouse, clicking the button shows **Please select a warehouse first.**
  - If Issue Qty is missing or not greater than zero, clicking it shows **Please enter an Issue Qty greater than 0 first.**
- **Untracked line:** shows **Not Required**.

A line-level batch-tracking validation prevents submission when any line with Issue Qty greater than zero has no batch. The exact error is **Please select a batch for all batch-tracked items**.

A serial-tracking validation prevents submission when any line with Issue Qty greater than zero does not have exactly that many selected serial numbers. The exact error is **Please select exactly the right number of serial numbers for all serial-tracked items.**

### 8.3 GIN remarks and footer

Below the table is:

- Label: **GIN Remarks**
- A two-row textarea.

The footer contains:

- **Cancel**, which closes the fulfillment modal.
- **Dispatch Goods & Generate Invoice**, which submits the form and shows a loading state while submitting.

The client builds a fulfillment payload containing warehouse ID, dispatch date, remarks or `null`, and only lines whose parsed Issue Qty is greater than zero. Each submitted line includes its sales-order-line ID, batch ID or `null`, serial IDs for serial-tracked lines (otherwise an empty array), dispatch quantity, and line remarks or `null`.

On success, the form shows **Goods dispatched successfully**, calls its success callback, closes the modal, and refreshes the order list. An unsuccessful response shows its message or **Fulfillment failed**. A thrown error shows its message or **An error occurred**.

## 9. Serial Number Selection modal in fulfillment

The fulfillment form opens this modal for a serial-tracked line.

### 9.1 Fields and table

- Modal title: **Select Serial Numbers**
- Size: `lg`
- Search input placeholder: **Search serial numbers...**
- Selection counter: **Selected: `<count>` / `<required quantity>`**
- Table columns:
  1. **#** — checkbox
  2. **Serial Number**
  3. **Status**

When loading, the table shows a three-column loader. When no results are returned, it shows **No serial numbers found.** Each result row shows the serial number and status and can be selected by clicking the row or checkbox.

### 9.2 Search, selection, and pagination

- Search is debounced by **500 ms**, and a changed search returns to page 1.
- Requests are made only while the modal is open and both warehouse ID and item ID are present.
- The request filters for available serials and includes item ID, warehouse ID, page, and a page size of 10. Variant ID and search text are included when present.
- Pagination appears when results have a positive total count and uses a page size of 10.
- The selected set is initialized from the previously selected serial IDs when the modal opens.
- Selecting more than the required quantity is blocked with **You only need to select `<required quantity>` serial number(s).**
- **Confirm Selection** is disabled unless the selected count exactly equals the required quantity.
- Clicking the confirmation action also checks for an exact match. If the count is wrong, it shows **Please select exactly `<required quantity>` serial number(s). Currently selected: `<count>`**.
- The footer buttons are **Cancel** and **Confirm Selection**.
- A successful selection is passed back to the fulfillment line and the modal closes.

## 10. Insufficient Stock modal

When confirming an order returns system code `INSUFFICIENT_STOCK`, the page opens a modal:

- Title: **Insufficient Stock**
- Size: `md`
- Body text: **The Sales Order cannot be saved because there is insufficient stock for the following items:**
- Table columns:
  1. **Item**
  2. **Needed Qty**
  3. **Available Qty**
  4. **Shortage**

Each row displays the item name, and when present, its variant name and **Batch: `<batch number>`**. Needed quantity, available quantity, and shortage are formatted to two decimal places; shortage is calculated in the UI as needed quantity minus available quantity.

The modal footer has a **Close** button. Closing it clears the shortage state.

This modal is opened by the **confirm** action’s response handling. The text says “cannot be saved,” but the call site is specifically confirming an existing draft order.

## 11. Other source components and what is not part of the rendered page

A `SalesOrderForm.tsx` component is present in the supplied source. It contains a separate basic form with Customer, Order Date, Expected Delivery, line item ID/variant ID/quantity/price/discount/tax inputs, Remarks, and Create/Update buttons. However, the shown `SalesOrderList` does not import or render `SalesOrderForm`; it uses `ProductTransactionScreen` instead. The basic form must therefore **not** be described as the active create/edit screen for this page.

The shared transaction component’s batch, serial, and parent-line modal implementations are not included, even though some are referenced by the supplied Product Selection Panel. Their internal fields and exact modal text are not available from the provided code.

## 12. API and data flow

### 12.1 List and settings requests

On initial render, the page starts both list loading and Sales settings loading.

The list request calls `getSalesOrders` with:

- `page`
- `per_page: 15`
- `search`
- `status` only when a status filter is selected

A successful response populates the list and reads pagination values from either `result.meta` or the fallback result fields. A thrown list error shows its message or **Failed to load orders**. Loading is cleared in either case.

The settings request calls `getSalesSettings` and stores its result. A settings failure is written to the console as **Failed to load settings**; the supplied code does not show a user-facing toast for that failure.

The backend list service:

- Limits results to the active organization.
- Supports search, status, party ID, date-from, date-to, source, and page size.
- Orders by creation time descending.
- Returns customer and warehouse information and a goods-issue-note count.

The page itself sends only search, status, page, and page size in its list request.

### 12.2 Detail, edit, and fulfillment reads

- `openDetail` calls `getSalesOrder(order.id)` and replaces the selected list row with the returned full order on success.
- `handleEdit` also calls `getSalesOrder(order.id)`, then maps its lines into transaction-screen initial data.
- `handleFulfill` calls `getSalesOrder(order.id)` and uses the full result for the fulfillment form.
- Detail loading errors are handled differently by path:
  - Opening details suppresses the caught exception in the shown code and clears loading.
  - Editing shows **Failed to load order details** for an unsuccessful response, or an error message/general loading error for a thrown exception.
  - Fulfillment shows **Failed to load order details** for an unsuccessful response, or an error message/general error for an exception.

The backend resource can provide order identifiers, number, dates, totals, status, source, remarks, warehouse ID, customer and warehouse summaries, lines, goods issue notes, invoice summary, goods-issue-note count, and fulfillment progress when the relevant relationships/data are loaded. Line resources include quantities, fulfillment and remaining quantities, price/discount/tax/subtotal, free quantity, serial numbers, parent references, remarks, and loaded item, variant, unit, and batch details.

### 12.3 Mutations

The page calls the following client methods:

- `createSalesOrder` for a new order.
- `updateSalesOrder` for an edited order.
- `deleteSalesOrder` for draft deletion.
- `confirmSalesOrder` for draft confirmation.
- `cancelSalesOrder` for cancellation.
- `fulfillSalesOrder` for dispatch, from `FulfillmentForm`.

On successful delete, confirm, or cancel, the page displays respectively:

- **Order deleted**
- **Order confirmed**
- **Order cancelled**

Each successful operation refreshes the order list. Failed responses display their returned message or the relevant fallback. The confirm handler treats `INSUFFICIENT_STOCK` specially by opening the stock-shortage modal rather than showing the normal failure toast.

### 12.4 Supporting lookups

The supplied shared transaction code also calls supporting lookup functions, conditional on configuration or user interaction:

- `transactionLookup` for product searches.
- `getItemBatches` for batch options.
- Price-list checks and price evaluation for sales-type transactions.
- Payment-mode and bank-account lookups if payment controls are enabled.
- Currency and base-currency lookups if currency controls are enabled.
- Serial-number lookup for the fulfillment serial modal.
- `getSalesSettings` to provide the Sales-unit setting.

The supplied Sales Orders page does not show API URL paths for these client methods, so no endpoint paths are asserted here.

## 13. Backend validations and business rules

The following rules are explicitly present in the supplied request, controller, or service code. They are separate from client-side UI behavior.

### 13.1 Store request validation

- `party_id` is required, must be an integer, and must exist as a party.
- `warehouse_id` is nullable. If supplied, it must be an integer and exist within the organization identified by the organization context.
- `order_date` is required and must be a date.
- `expected_delivery` is nullable, must be a date when supplied, and must be on or after `order_date`.
- `remarks` is nullable and must be a string.
- `lines` is required, must be an array, and must contain at least one entry.
- Every line’s `item_id` is required, must be an integer, and must exist as an inventory item.
- `variant_id` is nullable, must be an integer when supplied, and must exist as a variant.
- A line’s `quantity` is required, numeric, and at least `0.0001`.
- `unit_price` is required, numeric, and at least zero.
- `unit_discount` is nullable, numeric, and at least zero.
- `tax_rate` is nullable, numeric, and between zero and 100 inclusive.
- Line `remarks` is nullable and must be a string.
- `uom_id` is nullable, must be an integer when supplied, and must exist as a unit of measure.
- `is_free_qty` is nullable and must be boolean when supplied.
- `parent_line_uids` is nullable and must be an array when supplied.
- `uid` is nullable and must be a string when supplied.
- `batch_id` is nullable, must be an integer when supplied, and must exist as a batch.
- `serial_numbers` is nullable and must be an array when supplied.

Additional request validation:

- If an item has variants, a variant is required. The exact error is **Variant is required for this item.**
- If a supplied variant belongs to a different item, validation fails with **The selected variant does not belong to the selected item.**

These additional checks look up the item and variant in the organization context.

### 13.2 Organization context and controller behavior

The controller resolves organization context from the `X-Organization-Id` request header, then the `organization_id` input, and then the authenticated user’s first organization.

- List and create return an error if organization context cannot be resolved; the message is **Organization context is required.**
- Reads and mutations are performed with the resolved organization ID in the service calls.
- A missing order in the show action returns **Sales order not found**.
- Update and delete convert certain service exceptions to API error/conflict responses, as shown in the controller.

### 13.3 Create calculations and initial status

On creation, the service:

- Creates a Sales Order in **draft** status with source **manual**.
- Generates the order number through the document-number service.
- Calculates each line subtotal from quantity, unit price, and unit discount.
- Calculates tax from line subtotal and tax rate.
- Totals subtotal, tax, discount, and grand total.
- For a line marked `is_free_qty`, forces unit price, unit discount, and tax rate to zero.
- Resolves parent-line UIDs to created line IDs for free-quantity lines when the referenced UIDs match created lines.

The create path initializes line serial numbers to `null` in the service code, despite the request accepting a `serial_numbers` array. This is a server-side implementation detail of the supplied code; it should not be mistaken for a guarantee that submitted serial selections are stored on the created order.

### 13.4 Update, delete, confirm, and cancel rules

- Only draft sales orders can be edited. Otherwise the service returns **Only draft sales orders can be edited.**
- Only draft sales orders can be deleted. Otherwise the service returns **Only draft sales orders can be deleted.**
- Only draft sales orders can be confirmed. Otherwise the service returns **Only draft sales orders can be confirmed.**
- Only confirmed or partially shipped sales orders can be cancelled. Otherwise the service returns **Only confirmed or partially shipped sales orders can be cancelled.**
- Cancellation is rejected if the order has any goods issue notes, with **Cannot cancel a sales order that has been partially or fully fulfilled.**
- On cancel, the service releases reserved stock for the order.
- On confirm, the service validates stock availability and reserves stock. If stock validation reports shortages, it returns an `INSUFFICIENT_STOCK` validation response with shortage data.

### 13.5 Stock validation and reservation

The supplied service code’s confirmation logic:

- Builds stock requirements from order lines, accounting for a line’s unit conversion factor when present.
- Skips items that do not have stocks.
- For items that allow phantom BOM, it expands the requirement into the phantom BOM materials when a non-empty BOM exists.
- Groups requirements by item, variant, and batch.
- Includes item, variant, and batch display details in shortage requirements where available.
- Calls the stock service to validate availability for the order warehouse.
- If shortages are returned, confirmation does not proceed to the confirmed status.
- If stock validation succeeds, the service reserves stock and then updates the order to confirmed.

The supplied code does not state a universal maximum order quantity or maximum discount amount. Do not infer either.

## 14. UI behavior versus backend rules

Some limits or checks described on this page are client-side behaviors rather than rules in the supplied `StoreSalesOrderRequest`:

- The shared discount UI clamps percentage discounts to 0–100 and limits amount discounts per unit to the unit price. The backend request explicitly validates `tax_rate` to 0–100, but does not provide an equivalent maximum rule for `unit_discount`.
- The shared quantity input has UI `min={0.001}`, while the backend request requires a minimum of `0.0001`.
- The fulfillment form checks that a warehouse is selected, batch-tracked issued lines have a batch, and serial-tracked issued lines have exactly one selected serial per unit of Issue Qty. No corresponding fulfillment backend request validation was supplied, so these are documented as client-side checks only.
- The serial-number modal enforces an exact selection count in the UI. The supplied Sales Order store request only specifies that `serial_numbers` is nullable and an array; it does not state an exact-count validation rule there.
- The Sales Orders UI hides edit and delete actions for non-draft orders and hides cancellation except for confirmed orders. The backend service has its own status checks as listed above.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---

## Feature: CREDIT-NOTES

# Credit Notes — Sales UI Guide

## 1. Global navigation and entry flow

The supplied global menu includes this page under Sales:

- **Module:** Sales
- **Menu group:** Post-Sales
- **Menu label:** Credit Notes
- **Route:** `/sales/credit-notes`

The route is therefore a listed Sales sidebar destination, not a hidden/internal route. The code supplied documents only this page; it does not show links from other Sales pages into Credit Notes.

## 2. Overview

The page lists credit notes associated with sales returns. Users can search and filter the list, inspect a credit note’s details and settlement history, and—when the note is not marked `paid`—open a payment form to log a payment.

There is no control here to create a credit note. Creation is not shown in this page’s code.

**CRITICAL NOTE**: This is a view-only page. Users cannot manually create a credit-notes here.

This note concerns creating credit notes: the page does include a **Log Payment** action for eligible notes.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

## 3. Page layout and visible elements

### Page heading

At the top of the page:

- Heading: **Credit Notes**
- Supporting text: **Manage credit notes issued against sales returns.**
- A `RecordCount` component displays the total record count when the page is not loading. Its detailed visual format is not shown in the supplied code.

### Status filter controls

Four buttons are rendered:

- **All** — sends an empty status filter.
- **Unpaid** — filters using `unpaid`.
- **Partial** — filters using `partially_paid`.
- **Paid** — filters using `paid`.

The selected filter uses a dark background and white text; the other filters use a light background and muted text. Selecting any filter sets the page to page 1 and causes the list request to be refreshed.

### Search control

A `DesktopSearchPopover` is rendered with:

- Placeholder: **Search by CN #, customer...**
- Current input value: `searchTerm`
- Change handler: updates `searchTerm`

The search value is debounced by 500 milliseconds. After the delay, the debounced value is applied and the page is reset to page 1. The code does not expose the popover’s internal layout or any additional fields.

### Credit-note table

The table has eight columns, in this order:

1. **CN #** — credit-note invoice number.
2. **Ref#** — source reference number; displays `-` if absent.
3. **Customer** — party full name; displays `-` if absent.
4. **Date** — invoice date formatted using the browser’s locale; displays `-` if absent.
5. **Amount** — absolute value of `amount_due`.
6. **Settled** — absolute value of `amount_settled`.
7. **Balance** — calculated from the absolute due amount minus the absolute settled amount.
8. **Status** — a badge based on the note status.

Each row is clickable and opens the credit-note details modal.

#### Amount formatting and status display

The amount formatter converts the input to a number, uses its absolute value, and formats it with locale-specific grouping and at least two fractional digits.

Known status-to-badge mappings are:

- `unpaid` → **Unpaid**, danger color
- `partially_paid` → **Partial**, warning color
- `paid` → **Paid**, success color

Any status not found in this mapping is displayed using the `unpaid` mapping. The balance text is red when the calculated outstanding amount is greater than zero; otherwise it is gray.

#### Loading, empty, and pagination states

- While loading, the table displays `TLoader` configured for eight columns.
- If loading has finished and there are no returned invoices, the table displays **No credit notes found.**
- Pagination is shown only when loading has finished and the current result contains at least one invoice.
- Pagination receives the current page, total item count, a page size of 15, and a callback that updates the page.

The `RecordCount` is also hidden while loading.

## 4. Credit Note Details modal

Clicking a table row opens the modal titled **Credit Note Details**. The selected list record is shown immediately while the page requests the full invoice record. The modal receives `viewingInvoice?.entity_id` as its `entityId`.

### Header details

The modal displays:

- The credit-note invoice number.
- The party’s full name, or **Unknown** if missing.
- A status badge using the same status mapping and fallback as the table.

### Summary fields

Four summary items are rendered:

- **Total Amount** — formatted absolute `amount_due`.
- **Settled** — formatted absolute `amount_settled`.
- **Balance** — absolute due amount minus absolute settled amount, passed through the same absolute-value formatter.
- **Date** — locale-formatted invoice date, or `-` if absent.

### Settlement History

This section appears only when `viewingInvoice.payments` exists and has at least one item. It contains a table with these columns:

- **Date** — formatted payment date, or `-`.
- **Method** — `payment_method`.
- **Amount** — formatted absolute `payment_amount`.
- **By** — creator’s name, or `-`.

### Modal actions

For an invoice whose status is anything other than `paid`, the footer contains:

- **Close** — closes the details modal.
- **Log Payment** — opens the payment modal for the current invoice and closes the details modal.

For an invoice whose status is `paid`, the footer contains only:

- **Close** — closes the details modal.

The code checks specifically for `status !== "paid"` before showing **Log Payment**. It does not restrict that action only to the known `unpaid` and `partially_paid` values.

## 5. Log Payment modal

The payment modal:

- Opens when the user selects **Log Payment** from an eligible credit note’s details.
- Uses the title format **Log Payment — {invoice number}**.
- Has size `md`.
- Closes through its `onClose` handler or the form’s cancel callback.

The page passes the following props into `PaymentForm`:

- `invoice` — the selected credit note.
- `onSuccess` — closes the payment modal and refreshes the credit-note list.
- `onCancel` — closes the payment modal.
- `onRecordPayment` — the `logPayment` function.
- `fetchPaymentModes` — the `getPaymentModes` function.
- `fetchBankAccounts` — the `getBankAccountsLookup` function.
- `fetchChequeLeaves` — the `searchAvailableChequeLeaves` function.

The implementation of `PaymentForm` is not included in the provided source. Therefore, its internal labels, inputs, choices, validation, buttons, and submission behavior cannot be documented from this code alone. The code does establish that the form is supplied with payment-recording and payment-mode, bank-account, and cheque-leaf lookup callbacks.

## 6. Step-by-step workflows

### Find and filter credit notes

1. Open **Sales → Post-Sales → Credit Notes**, at `/sales/credit-notes`.
2. The page requests the first 15 matching records.
3. To filter by status, select **All**, **Unpaid**, **Partial**, or **Paid**.
4. The page resets to page 1 and requests records using the selected status.
5. To search, enter text through the search popover. The request uses the updated search value after a 500 ms delay, and the page resets to page 1.
6. If results span multiple pages, use the pagination control, which is displayed when the current page has records and loading has finished.

### Inspect a credit note

1. Select a row in the table.
2. The details modal opens immediately using the row’s available data.
3. The page requests the full invoice by ID.
4. If the request succeeds with a result, the modal is updated with that result.
5. Review the header, summary, and—if payment records exist—Settlement History.
6. Select **Close** to dismiss the modal, or select **Log Payment** if that action is displayed.

### Log a payment

1. Open a credit note’s details.
2. If its status is not `paid`, select **Log Payment**.
3. The details modal closes and the **Log Payment — {invoice number}** modal opens.
4. The supplied `PaymentForm` is rendered with the invoice and the payment-related callbacks.
5. On the form’s success callback, the payment modal closes and the list is refreshed.
6. On the form’s cancel callback, the payment modal closes without the success refresh being invoked by that callback.

The actual payment form fields and the behavior of its submission are not visible in the supplied source.

## 7. API and data flow

### List request

The page calls `getInvoices` with these parameters:

- `page` — current page.
- `per_page` — fixed at `15`.
- `search` — debounced search value.
- `type` — fixed at `ar`.
- `document_type` — fixed at `credit_note`.
- `source` — fixed at `sales_order,pos`.
- `transaction_category` — fixed at `sales_return`.
- `status` — included only when a status filter has been selected.

When the response has `is_success` and a `result`, the page:

- Sets the displayed invoice list from `result.data`, falling back to an empty array.
- Sets the total count from `result.meta.total`, or, if absent, `result.total`, or, if both are absent, `0`.

A rejected request displays `e.message`, or **Failed to load** if there is no message. Loading is cleared in the `finally` path. The code does not specify a separate error-screen layout.

### Detail request

Selecting a row calls `getInvoice(inv.id)`. The selected row is put into modal state before the request completes. If the request succeeds and includes a result, that result replaces the selected row data. Errors from this detail request are silently ignored by the shown `catch` block.

### Payment-related calls

The page passes `logPayment`, `getPaymentModes`, `getBankAccountsLookup`, and `searchAvailableChequeLeaves` to `PaymentForm`. Their request formats, response handling, and validation are not defined in this page’s supplied code.

## 8. Backend validations and business rules

No `--- EXTRACTED BACKEND VALIDATIONS ---` content or backend implementation was supplied. Consequently, no backend validation rules, limits, or rejection behavior can be confirmed from the provided material.

The following are **page-level behaviors visible in the React code**, not claims about backend validation:

- The list request is scoped by `type: 'ar'`, `document_type: 'credit_note'`, `source: 'sales_order,pos'`, and `transaction_category: 'sales_return'`.
- The list page size is 15.
- Search is debounced by 500 ms.
- The status filter is optional and uses the values `unpaid`, `partially_paid`, and `paid`.
- The **Log Payment** action is hidden only when the displayed invoice status is exactly `paid`.
- Amounts are formatted using absolute values in the UI. The code does not establish a backend amount rule.
- No discount control appears in this page’s code, so no discount behavior or discount-disabled conditions are specified here.
- No credit-note creation form or save/create action appears in this page’s code.

---

## Feature: QUOTATIONS

# Sales Quotations — UI and Workflow Guide

## 1. Global navigation and entry flow

- The global menu includes **Quotations** under **Sales → Orders**.
- Its listed route is **`/sales/quotations`**.
- This is a sidebar-listed Sales page, not a hidden/internal route.
- The quotation creation screen, quotation details view, price-list update modal, and insufficient-stock modal are component states rendered within this page. The supplied code does not define separate routes for them.
- The source also calls `getSalesSettings()` to obtain Sales settings. The settings page or navigation path is not part of this quotations code, so this guide does not infer one.

## 2. Overview

The page lists and manages sales quotations. A user can:

- Search and filter the quotation list.
- Open quotation details.
- Create a quotation.
- Revise a quotation in eligible statuses.
- Send, accept, reject, cancel, delete, or convert a quotation when its status makes the relevant action available.
- See stock-shortage details if an attempted conversion fails because the API reports insufficient stock.

The page’s description reads:

> Create and manage pre-sale quotations for customers.

The page includes an explicit **New Quotation** action and a shared transaction form with a submit button. **It is not view-only.**

## 3. Pages, views, and conditional screens

The supplied code defines one page route, `/sales/quotations`, with these rendered views:

1. **Quotations list** — the default view.
2. **New Sales Quotation** — shown after selecting **New Quotation**.
3. **Revising Quotation [SQ number]** — the same transaction-screen view populated from an existing quotation.
4. **Quotation Details** — a detail modal.
5. **Price List Update** — a modal that can appear in the transaction screen when changing the selected party would change applicable prices.
6. **Insufficient Stock for Conversion** — a modal that appears if conversion returns the `INSUFFICIENT_STOCK` system code.

These are conditional states of the supplied page, not separately declared routes.

---

# 4. Quotations list

## 4.1 Page heading and controls

The list view displays:

- Heading: **Sales Quotations**
- Description: **Create and manage pre-sale quotations for customers.**
- A record count, shown when the list is not loading.
- A mobile search/options control with:
  - Search label: **Search Quotations**
  - Placeholder: **Search by SQ #, customer...**
  - Search value tied to the page’s search term.
  - A **New Quotation** dropdown item with a plus icon.
- A desktop/table toolbar containing:
  - Another record count, shown when the list is not loading.
  - Six status-filter buttons:
    - **All**
    - **Draft**
    - **Sent**
    - **Accepted**
    - **Converted**
    - **Rejected**
  - A desktop search popover with placeholder **Search by SQ #, customer...**
  - A **New Quotation** button with a plus icon.

Selecting a status filter sets the status used for the next list request and resets the page number to 1. **All** uses an empty status value, so no status parameter is added to the list request.

The UI does not provide filter buttons for every backend status. In particular, **Expired**, **Cancelled**, and **Revised** do not have dedicated filter buttons in the supplied code.

## 4.2 Search behavior

Both search controls use the same `searchTerm` state.

- Search changes are debounced for **500 ms**.
- After the debounce, the debounced search value is updated and pagination resets to page 1.
- The list request sends the debounced text as `search`.
- The backend list service matches the search text against the quotation number and the customer’s first or last name.
- The UI does not expose separate customer, date-range, or party filters.

While search is waiting for its debounce, the list continues to use the previous debounced search value.

## 4.3 Table columns

The table has seven columns:

1. **SQ #**
   - Displays `q.sq_number`.
   - If the status is `revised`, the number is rendered with line-through styling and muted text.

2. **Customer**
   - Displays `q.customer?.name`.
   - If that value is absent, displays a dash (`-`).

3. **Date**
   - Displays `q.quotation_date` through `DateLabel`.
   - If there is no quotation date, displays `-`.

4. **Valid Until**
   - Displays `q.valid_until` through `DateLabel`.
   - If there is no validity date, displays `-`.

5. **Grand Total**
   - Displays the formatted `q.grand_total`.
   - The UI formats the number with two decimal places.

6. **Status**
   - Displays a flat badge. The code maps statuses to these labels and colors:
     - `draft` → **Draft**, default
     - `sent` → **Sent**, primary
     - `accepted` → **Accepted**, success
     - `rejected` → **Rejected**, danger
     - `expired` → **Expired**, warning
     - `converted` → **Converted**, success
     - `cancelled` → **Cancelled**, danger
     - `revised` → **Revised**, default
   - An unrecognized status falls back to the Draft badge configuration.

7. **Actions**
   - Contains a three-dot dropdown.
   - Clicking in this actions cell stops the row click from opening the quotation details.

## 4.4 Loading, empty, and pagination states

- While loading, the table renders a loader configured for seven columns.
- If loading has finished and there are no quotations, the table displays **No quotations found.**
- Pagination appears only when:
  - Loading has finished, and
  - At least one quotation is present.
- Pagination uses:
  - Current page state.
  - Total item count from the list response.
  - **15** items per page.
- Changing page updates the page state, which triggers another list fetch.
- The request also sends `per_page: 15`.

## 4.5 Row interaction

Clicking a quotation row calls the detail-opening flow:

1. The selected row’s quotation is immediately placed in the detail state.
2. A detail fetch is started using `getSalesQuotation(q.id)`.
3. If that response succeeds and contains a result, the detail state is replaced with the fetched result.
4. The detail-loading state is then cleared.
5. The supplied JSX does not show a separate loading message or spinner inside the detail body based on `viewLoading`; it only records the loading state.

---

# 5. Actions in the list row dropdown

Every row’s action dropdown includes **View Details**. Other actions are conditional on quotation status.

## 5.1 View Details

- Text: **View Details**
- Icon: eye
- Opens the quotation detail modal for that quotation.
- The row action does not rely solely on the list data: it also calls `getSalesQuotation(id)`.

## 5.2 Draft quotation actions

For a quotation whose status is `draft`, the dropdown includes:

### Send

A confirmation control is displayed with:

- Title: **Send Quotation?**
- Body: **This will mark the quotation as sent to the customer.**
- Action label: **Send**

Confirming calls `sendSalesQuotation(id)`. On a successful response, the UI:

- Shows the toast **Quotation sent**.
- Refreshes the quotation list.
- If that quotation is currently open in the details modal, replaces its detail state with the response result.

### Delete

A confirmation control is displayed with:

- Title: **Delete Quotation?**
- Body: **This will permanently delete the quotation.**
- Action label: **Delete**

Confirming calls `deleteSalesQuotation(id)`. On success, the UI:

- Shows **Quotation deleted**.
- Refreshes the list.

If the response is unsuccessful, the UI shows the response message or **Failed to delete**. If the call throws, the UI shows the thrown message or **An error occurred**.

## 5.3 Sent quotation actions

For a quotation whose status is `sent`, the dropdown includes:

### Accept

Confirmation text:

- Title: **Accept Quotation?**
- Body: **This will approve the quotation for conversion.**
- Action label: **Accept**

On success, the UI shows **Quotation accepted**, refreshes the list, and updates the open detail state if it is the same quotation.

### Reject

Confirmation text:

- Title: **Reject Quotation?**
- Body: **This will reject the quotation.**
- Action label: **Reject**

On success, the UI shows **Quotation rejected**, refreshes the list, and updates the open detail state if it is the same quotation.

## 5.4 Accepted quotation action

For a quotation whose status is `accepted`, the dropdown includes **Convert to SO**, with a confirmation:

- Title: **Convert to Sales Order?**
- Body: **This will create a new Sales Order from this quotation.**
- Action label: **Convert to SO**

This calls `convertQuotationToOrder(id)`. Its success and failure behavior is described in [Conversion to a Sales Order](#10-conversion-to-a-sales-order).

## 5.5 Cancel action

The dropdown includes **Cancel** when the status is not:

- `converted`
- `cancelled`
- `revised`

The confirmation says:

- Title: **Cancel Quotation?**
- Body: **This action cannot be undone.**
- Action label: **Cancel**

On success, the UI shows **Quotation cancelled**, refreshes the list, and updates the open detail state if it is the same quotation.

The list UI’s condition means a draft, sent, accepted, rejected, or expired quotation can be offered a Cancel action. Whether the backend accepts a particular status is determined by its service behavior; the supplied service explicitly blocks cancellation only when the quotation is already converted.

## 5.6 Actions not shown in the list dropdown

The list dropdown does **not** show:

- **Revise** — revision is available from the detail modal for specified statuses.
- **Edit** — although the API controller and service contain an update operation for draft quotations, this page’s supplied UI does not expose a draft-edit action.
- A send/accept/reject/convert action for statuses other than the specific conditions above.

---

# 6. New quotation screen

## 6.1 Opening and leaving the screen

Selecting **New Quotation** from either the mobile options menu or desktop toolbar sets the create-screen state and replaces the list view with the transaction form.

The screen header contains:

- A back-arrow button.
  - Clicking it returns to the list view.
  - It clears any `reviseQuotation` state.
- Heading: **New Sales Quotation**
- Supporting text: **Select products, set quantities and pricing for a quotation**

The same screen has a different title when opened for revision; see [Revising a quotation](#8-revising-a-quotation).

## 6.2 Shared `ProductTransactionScreen`

The page renders `ProductTransactionScreen` with:

- The `quotation` transaction preset.
- `enableSalesUnit` overridden from `salesSettings?.enable_sales_unit`.
- `disablePartySelection` set to true when revising.
- `disableWarehouseSelection` set to true when revising.
- Revision data passed as `initialData` when revising.
- `handleTransactionSubmit` as the form submission callback.

The code provided does not include the actual values in `TRANSACTION_PRESETS.quotation`. Consequently, fields controlled by preset flags are described below as conditional: the shared component renders them only when the corresponding configuration property enables them. The page-level code specifically establishes the quotation type and the Sales-unit setting, but does not show every preset flag.

## 6.3 Product selection area

The shared component renders a `ProductSelectionPanel`.

### Product search

When item selection is enabled by the configuration, the panel contains:

- A product search input.
- Placeholder:
  - **Select a warehouse first to search items...** if `requireWarehouseFirst` is true and no warehouse is selected.
  - Otherwise, **Search by name, SKU, or scan barcode...**
- A loading icon while a search request is in progress.
- An auto-add toggle with a hint:
  - **Automatically adds an item to the list when a barcode is scanned or an exact match is found.**
  - Auto-add is initially enabled.
- A create-item icon button is rendered only if an `onAddNewItem` callback is provided. The quotations page does not pass that callback in the shown JSX, so this optional button is not established as present on this page.

Search behavior in the shared component:

- Search begins after a **250 ms** delay.
- An empty search clears results and hides the result panel.
- Requests ask for up to 20 results and include the transaction type.
- If a warehouse is selected, its ID is sent with the item lookup.
- For `sales`, `quotation`, or `pos` types, the lookup also requests Sales pricing; if a party is selected, its ID is included.
- If auto-add is on and the lookup returns an exact match:
  - Serial matches are added with the matching serial number.
  - Batch matches in Sales/quotation/POS are added directly with a batch selection and quantity 1.
  - Variant matches are handled as an item-plus-variant selection.
  - Item matches are added as items.
- If there is no exact match, search results are displayed.
- If there are no results for a non-empty search, the panel displays **No items found for “[search value]”**.
- Search results can display:
  - Item image, or a package icon when no image is available.
  - Item name and SKU.
  - A variant-count badge when the item has variants.
  - Price when prices are enabled in the configuration.
  - Available stock when stock display is enabled and the item has stock information.
  - Variant rows with variant name, SKU, optional price and stock, and **Select**.
  - **No active variants found.** when an expanded item has no variants.
- The result list supports keyboard navigation with the up/down arrows, Enter, and Escape.

### Empty item area

If no lines have been added, the panel displays:

- A shopping-cart icon.
- **No items added**
- **Search for products above to add them**

### Line-item table

When lines exist, the item table includes:

- **Item**
- **Qty**
- **Unit**, only if purchase-unit or sales-unit selection is enabled.
- **Rate**, only if prices are enabled.
- **Disc.**, only if prices are enabled and the transaction type is `sales`, `quotation`, or `pos`.
- **Total**, only if prices are enabled.
- An unlabeled action column containing a remove-item button.

Each item row can show:

- Item image or package icon.
- Item name.
- A **Free** label for a free-quantity line.
- SKU or, for a variant item, variant name and SKU.
- For an item with variants but no selected variant:
  - A variant selector when item-level selection is not allowed.
  - An **Any Variant** indication when item-level selection is allowed.
- Tracking controls as applicable:
  - Batch selector for quotation/Sales/POS batch-tracked items.
  - Serial-selection control when serial selection is enabled.
- A **Free Quantity** checkbox in the shared component for eligible zero-priced lines; see [Free-quantity behavior](#67-free-quantity-and-parent-lines).
- A quantity input.
- A unit selector when the configuration enables a unit column.
- A rate input when prices are shown.
- A discount type selector and discount input when the discount column is shown.
- The line total.
- A **Remove Item** button.

The shared line table’s discount control is disabled under the exact conditions listed in [Discount control behavior](#65-discount-control-behavior).

### Batch selection for quotation lines

For Sales-module types—including quotation—batch-tracked lines use a batch selector in the line row:

- Placeholder: **Select Batch...**
- If a warehouse is present, an available-stock value can be shown alongside batch options.
- Batch options are loaded using the item’s batch lookup and may include the selected variant and warehouse.
- The selected batch’s selling price is used to update the line price when one is selected.
- Clearing the selection removes the line’s batch selection.
- If no batch is selected, the line is considered batch-pending by the shared component.
- A warning icon is shown when the line has no selected batches.

The shared component also contains batch-selection-modal code used by other configuration paths. For quotation’s Sales-type behavior, selecting an item with batch tracking adds it directly; the line-row selector is the visible batch-selection mechanism in the supplied code.

### Serial and parent-line dialogs

The shared component contains modal integrations for:

- Serial selection.
- Batch selection.
- Selecting parent lines for a free-quantity line.

The supplied excerpts do **not** include those modal components’ internal form fields or modal text, so their inner contents cannot be specified from this source. The calling code establishes their opening conditions and callbacks, but not their detailed presentation.

### Item count and units summary

When at least one line exists, the panel displays:

- The number of items, with singular/plural wording.
- The total number of units, calculated using each line’s quantity and the selected unit’s conversion factor when available.
- A formatted line-total sum when prices are shown.

## 6.4 Line-entry controls and calculations

The shared component implements these behaviors:

- Quantity input changes are converted to a number; the update handler clamps quantity to at least zero.
- The quantity input has HTML attributes `min={0.001}` and `step="any"`.
- Rate edits accept text matching a number with up to two decimal places; the update handler clamps the rate to at least zero.
- Changing a unit can recalculate the rate based on the old and new unit conversion factors.
- When a line has price rules and its quantity, unit, batch, or free-quantity state changes, the shared component can recalculate its rate and discount from those rules.
- A manual rate override clears the displayed applied price rule.
- If a line has exactly one selected batch and its quantity changes, that batch’s quantity is updated to match.
- Removing a line also removes its UID from other lines’ parent-line selections.
- The shared component’s subtotal is the sum of rate × quantity; its discount total is the sum of line discount amounts; its grand total is subtotal minus discount total.

A POS-only amount-to-pay summary is rendered only when the transaction type is `pos`, so it is not established as part of this quotation screen.

## 6.5 Discount control behavior

The discount column is only rendered when prices are shown and the transaction type is one of `sales`, `quotation`, or `pos`.

For each line, the shared component disables both the discount type selector and discount input if **any** of these conditions is true:

1. `config.allowEditPrice` is false.
2. The line is marked as free quantity.
3. The transaction is a Sales-module type (`sales`, `quotation`, or `pos`) and the item’s `is_discountable` value is false.
4. The line’s unit price is exactly zero.
5. The line is a Sales-module batch-tracked item with no selected batch (`isBatchPending`).

The displayed selector options are:

- **Amt**
- **%**

The discount input:

- Uses the per-unit discount amount when the type is **Amt**.
- Uses the discount percentage when the type is **%**.
- Has placeholder **0.00** and `min={0}`.

UI calculations and limits:

- Amount entry is clamped between zero and the unit price. The resulting per-unit amount is multiplied by quantity to get the line’s total discount.
- Percentage entry is clamped between **0 and 100** in the UI.
- Changing quantity, rate, or discount recalculates the displayed line total.
- These are shared-component UI behaviors. The supplied backend request rules separately specify a minimum of zero for `unit_discount` and a tax-rate range of 0–100; they do not specify a maximum discount amount or percentage.

## 6.6 Free quantity and parent lines

The shared component’s free-quantity checkbox is rendered when:

- The unit price is zero, and
- The transaction type is one of `purchase`, `grn`, `quotation`, `sales`, or `pos`.

For this quotation screen, the relevant type is `quotation`.

- Checkbox text: **Free Quantity**
- The checkbox is disabled when the line has a purchase-order, sales-order, or sales-quotation line reference.
- When marked free, the component sets unit price, discount amount, discount percentage, and line total to zero.
- A free line can display a parent-line selector button with the placeholder **Select Parent Line...**.
- Its hint says: **Select the original line item that this free quantity is associated with.**
- The parent-line button is also disabled when the line has one of the referenced purchase-order, sales-order, or sales-quotation line IDs.
- The available parent lines exclude the free line itself and other free-quantity lines.
- Removing a prospective parent line or changing a line away from free quantity updates parent references in the client state.

When the page revises a quotation, it creates fresh client-side UIDs for the lines and remaps existing parent-line references to those UIDs before passing the lines into the shared form.

## 6.7 Metadata panel

The shared transaction screen also renders a `MetadataPanel`. Which fields appear depends on the quotation preset’s configuration. The component’s available fields and conditions are:

### Party/customer picker

When `config.showParty !== false`, the panel renders a party picker unless the configuration instead identifies the party as a warehouse.

- Label comes from `config.partyLabel`.
- It is marked required unless the transaction type is `pos`.
- It is disabled when `config.disablePartySelection` is true.
- For quotation revision, the page explicitly sets this disabled flag.
- A party change can trigger Sales price-list evaluation when there are existing eligible lines.

The actual wording of the party label depends on the preset and is not included in the supplied code.

### Warehouse picker

Rendered when `config.showWarehouse` is true.

- Label: **Warehouse**
- Marked required in the shared component.
- Disabled when `config.disableWarehouseSelection` is true.
- For quotation revision, the page explicitly disables warehouse selection.

### Currency and exchange rate

Rendered only when `config.enableCurrency` is true and the required currency callbacks are provided.

- Currency picker.
- If the selected currency differs from the base currency:
  - Label: **Exchange Rate**
  - Required marker.
  - Rate input displaying the relationship `1 [selected currency code] = [input] [base currency code]`.
  - Input has `min="0.000001"` and `step="0.000001"`.

The shared component loads the base currency setting when currency support is enabled. Party selection can select the party’s default currency or reset to the base currency.

### Date

Rendered when the date callback is supplied.

- Section label: **Date**
- Date input, initialized in the shared component to the current date.
- In the quotation submit mapping, this becomes `quotation_date`; if the payload date is absent, the page uses the current date as a fallback.

### Expected-delivery date

Rendered when `config.showExpectedDeliveryDate` is true and its callback is supplied.

- Section label is the configured expected-delivery label, or **Expected Delivery** by default.
- Date input.
- In the quotation submit mapping, its value is used as `valid_until`, or null if absent. The UI label and backend field therefore have different wording.

### Supplier reference

Rendered when `config.showSupplierReference` is true and the callback is supplied.

- Section label: **Supplier Invoice No / Ref**
- Text input placeholder: **e.g. INV-2023-001**

The quotation submit mapping shown does not include this value in `sqData`.

### Notes

Rendered when `config.showNotes` is true.

- Section label: **Notes**
- Text area with two rows.
- Placeholder: **Add transaction notes...**
- The page maps this field to quotation `remarks`.

### Other expenses

Rendered only when `config.showOtherExpenses` is true and the supporting props are present.

- Button text: **Other Expenses (Couriers, Labor, etc.)**
- Displays a count badge if any expenses have been added.
- Opens the shared `OtherExpensesModal`.

The modal’s internal fields are not included in the provided source. The quotation submit mapping also does not send `other_expenses`.

### Totals

When prices are enabled, the transaction is not POS, and there is at least one line, the metadata panel displays:

- **Subtotal**
- **Discount**, only if the discount total is greater than zero
- **Grand Total**

These are shared-component calculations. The quotation page’s API submission mapping sends line fields and metadata but does not forward these displayed total values as quotation totals; the backend service calculates totals from the lines.

### Payments

Rendered only when `config.showPayment` is true.

- Section label: **Payment**
- The shared panel loads payment modes and bank-account lookup data when payment display is enabled.
- The `PaymentSection` internals and its exact controls are not supplied here, so they cannot be listed beyond the code shown in `PaymentEntryRow`:
  - Each payment entry has a mode name and icon.
  - **Amount** numeric input, with `step="0.01"` and `min={0}`.
  - A remove-payment button.
  - Additional fields are generated from the selected payment mode’s field configuration:
    - A `bank_account_select` field becomes a select with **Select...** and bank name/account-number options.
    - A configured number field becomes a number input.
    - A configured date field becomes a date input.
    - Other configured field types become text inputs.
    - Required configured fields display an asterisk.
- Payment submission, payment validation, and payment-related totals are controlled by configuration flags. The actual quotation preset values are not supplied, so payment controls cannot be asserted to be enabled for this screen.

### Submit button

The shared metadata panel includes a submit button labeled with `config.submitLabel`.

- It is disabled when there are no line items.
- It displays a loading state while submission is in progress.
- The exact quotation button text depends on the omitted preset configuration and cannot be stated from the provided code.

## 6.8 Price-list update modal

The shared transaction screen checks for active price lists for Sales, POS, and quotation transactions.

When changing the party while there are line items:

1. If there are active price lists, the component evaluates prices for eligible variant lines.
2. It compares the evaluated rates with current rates.
3. If it detects a price change, it opens a modal titled **Price List Update**.
4. The modal text and actions depend on its type:

**Confirm type**
- Message: **A few items have price changes based on the price list. Do you want to apply them?**
- Buttons: **No** and **Yes**
- Choosing **No**, or closing the modal, selects the pending party but does not apply the evaluated prices.
- Choosing **Yes** applies the evaluated prices and selects the pending party.

**Force type**
- Message: **Prices need to be changed based on the party selection.**
- Button: **OK**
- There is no **No** button for this type.
- Choosing **OK** applies the evaluated prices and selects the pending party.

When prices are applied, the UI shows **Prices updated based on party selection**. A failed evaluation displays **Failed to check prices**. The code chooses the force type when there was already a party selected and a line had a previously applied price rule; otherwise it chooses confirm.

---

# 7. Creating a quotation

1. Open **Sales → Orders → Quotations** using the listed route `/sales/quotations`.
2. Select **New Quotation** from the page toolbar or mobile options menu.
3. On the **New Sales Quotation** screen, select products using the product search, provided item selection is enabled by the quotation preset.
4. If an item has variants, select a variant unless the configuration allows item-level selection.
5. For batch-tracked quotation lines, use the line’s batch selector where required.
6. Set quantity, unit, rate, and discount where those controls are enabled.
7. Select or confirm the customer and warehouse if those pickers are rendered.
8. Enter dates, notes, or other metadata if the quotation preset displays those fields.
9. Select the transaction form’s configured submit button. It is disabled if no lines have been added.
10. The shared component validates its applicable UI conditions and calls the page’s `handleTransactionSubmit`.
11. The page maps the transaction payload into a quotation request:
    - `party_id`
    - `warehouse_id`
    - `quotation_date` from the transaction date, with today’s date as a fallback
    - `valid_until` from the expected-delivery date, or null
    - `remarks` from notes
    - `revised_from_id`
    - Lines containing item, variant, unit, batch, quantity, price, discount, zero tax rate, free-quantity state, parent-line UIDs, and UID
12. On successful creation:
    - A toast reads **Quotation [SQ number] created**.
    - The create screen closes.
    - Revision state is cleared.
    - The quotations list is fetched again.
13. If the API returns an unsuccessful result:
    - The UI shows the response message or **Failed to create quotation**.
    - The callback throws an error so the shared component treats submission as failed.
14. If the request throws, the page-level submission function does not show a page-specific catch toast in the supplied code. The shared component logs a warning and ends its submitting state.

The quotation request constructed by this page does not include `terms_and_conditions`, even though the backend accepts that field and the detail modal can display it when returned. No terms-and-conditions input is shown in the supplied quotation-screen JSX.

---

# 8. Revising a quotation

## 8.1 Which statuses can show the Revise action

The detail modal displays **Revise** for quotations whose status is:

- `sent`
- `accepted`
- `rejected`

There is no Revise action in the list dropdown. Other statuses do not receive the detail-modal Revise button in this code.

The backend service independently enforces that only sent, accepted, or rejected quotations can be revised.

## 8.2 What the revise action does in the UI

Selecting **Revise**:

1. Reads the currently viewed quotation.
2. Creates a client-side UID for each original line, using a `rev-...` value.
3. Builds initial form lines from the original quotation lines, including:
   - Item, with the original variant attached to the item’s variants when present.
   - Variant ID.
   - Unit-of-measure ID.
   - Quantity.
   - Unit price.
   - Total discount amount, calculated as `unit_discount × quantity`.
   - A discount percentage initialized to zero.
   - Line total from the original subtotal.
   - Free-quantity status.
   - New UID.
   - Initially empty parent-line UID list, followed by a remapping pass for any original parent references.
   - Collapsed state.
   - A batch entry if the original line has a batch, including its batch ID, batch number, quantity, and selling price when available.
4. Sets `revised_from_id` to the original quotation ID.
5. Closes the detail modal.
6. Opens the transaction screen with the title **Revising Quotation [SQ number]**.
7. Passes the original quotation data and reconstructed lines into `ProductTransactionScreen`.
8. Disables party and warehouse selection in the shared component for this revision form.

On submission, the page sends `revised_from_id` along with the quotation data. On successful creation, it shows the created-quotation toast and returns to the list.

## 8.3 Revision business behavior from the backend service

On creation with `revised_from_id`:

- The source quotation must belong to the resolved organization.
- The source status must be sent, accepted, or rejected; otherwise the service rejects the request with:
  - **Only sent, accepted, or rejected quotations can be revised.**
- The new quotation reuses the source quotation number.
- Its revision number is the source revision number plus one.
- The source quotation is marked `revised`.
- The new quotation is created in `draft` status.

---

# 9. Quotation Details modal

## 9.1 Modal identity and header

The page renders an `EntityDetailModal` with:

- Open state based on whether a quotation is selected.
- Close handler that clears the selected quotation.
- Title: **Quotation Details**
- `entity_id` from the selected quotation.

The supplied source does not include the internal implementation of `EntityDetailModal`; the following describes the content placed inside it by this page.

The modal body header shows:

- A file icon.
- Quotation number.
  - It is struck through and muted for `revised` quotations.
- Customer name, or **No customer**.
- A status badge using the status mapping listed in the table section.

## 9.2 Summary fields

The detail content displays:

- **Quotation Date**
  - Localized date when present.
  - `-` otherwise.
- **Valid Until**
  - Localized date when present.
  - `-` otherwise.
  - If `is_expired` is true, the date uses red text and the text **(EXPIRED)** is appended.
- **Revision**
  - Displays **Rev. [revision number]**.
  - Uses 1 if the revision number is absent or falsy.
- **Warehouse**
  - Warehouse name, or `-`.
- **Grand Total**
  - Formatted to two decimal places.

If `converted_so` exists, the modal also shows:

- **Converted To**
- The converted sales order number.

## 9.3 Line-item table

The line-item section is shown only when there is at least one line. Its heading is **Line Items**. Columns are:

1. **Item**
2. **Qty**
3. **Price**
4. **Disc.**
5. **Total**

Each row can display:

- Item name.
- If the item name is unavailable: **Deleted Item (ID: [item ID])**
- Variant name in parentheses when the line has a variant and the item indicates it has variants.
- A **Free** badge for free-quantity lines.
- For free lines with parent IDs, a **For:** label followed by the resolved parent item names and variant names. If a parent cannot be resolved, its ID is shown as `#[ID]`.
- Batch number as **Batch: [batch number]** when a batch exists.
- Quantity, followed by the unit abbreviation or name when available.
- Unit price, formatted to two decimal places.
- Unit discount, formatted to two decimal places; missing/falsy discount is treated as zero.
- Line subtotal, formatted to two decimal places.

## 9.4 Optional text sections

The modal displays these sections only when their values are present:

- **Terms & Conditions**
- **Remarks**

The supplied create form maps notes to remarks but does not show a terms-and-conditions input.

## 9.5 Detail-modal footer actions

The footer always contains:

- **Close** — closes the detail modal.

Additional buttons depend on status:

- `draft`: **Send**
- `sent`:
  - **Accept**
  - **Reject**
- `accepted`: **Convert to SO**
- `sent`, `accepted`, or `rejected`: **Revise**

The detail modal does not show **Cancel** or **Delete** buttons in the supplied code. Those actions are available, where applicable, from the list-row dropdown.

The detail buttons call their corresponding handlers directly. Unlike the list dropdown actions, the detail-modal actions do not use the shown `PopConfirm` controls.

---

# 10. Conversion to a Sales Order

## 10.1 UI entry point

**Convert to SO** is shown:

- In the list dropdown for `accepted` quotations, behind a confirmation.
- In the details modal for `accepted` quotations, as a direct button.

The list confirmation states:

- Title: **Convert to Sales Order?**
- Body: **This will create a new Sales Order from this quotation.**

## 10.2 Successful conversion

The page calls `convertQuotationToOrder(id)`.

When the response succeeds:

- A toast reads **Converted to SO: [SO number]**.
- The detail modal is closed.
- The quotation list is fetched again.

The backend service creates a Sales Order in draft status, transfers the quotation’s party, warehouse, totals, and lines, sets its source to quotation, and marks the quotation converted with the associated Sales Order. The Sales Order remarks are set to **Converted from Quotation [SQ number]**. Free-line parent references are remapped to the new order-line IDs.

## 10.3 Insufficient-stock result

If the conversion response is unsuccessful and its `system_code` is `INSUFFICIENT_STOCK`, the page stores the response result as stock shortages and displays a modal.

Modal text:

- Title: **Insufficient Stock for Conversion**
- Introductory message:
  - **The quotation cannot be converted to a Sales Order because there is insufficient stock for the following items:**

The shortage table has four columns:

1. **Item**
   - Item name.
   - Variant name, when present.
   - **Batch: [batch number]**, when present.
2. **Needed Qty**
3. **Available Qty**
4. **Shortage**
   - Calculated in the UI as needed quantity minus available quantity.

Quantities use two-decimal formatting. The modal footer contains **Close**, which clears the shortage state and dismisses the modal.

For other unsuccessful responses, the page shows the response message or **Failed to convert**. A thrown error displays its message or **An error occurred**.

---

# 11. API and data flow

## 11.1 List and settings fetches

On mount and when list dependencies change, the page calls `getSalesQuotations` with:

- `page`
- `per_page: 15`
- `search`
- `status` only when a filter is selected

On a successful response, the page reads:

- Rows from `result.data`, defaulting to an empty array.
- Last page from `result.meta.last_page`, falling back to `result.last_page`, then 1.
- Total count from `result.meta.total`, falling back to `result.total`, then 0.

On an exception, it logs the error and shows **Failed to fetch quotations**. Loading is cleared in a `finally` block.

The page separately calls `getSalesSettings()` and stores the result. If that call fails, it logs **Failed to load settings**; the supplied code shows no user-facing settings-error message.

## 11.2 Detail fetch

Opening a row or choosing **View Details** calls `getSalesQuotation(id)`. A successful result replaces the selected quotation state. The detail UI uses the returned fields described above.

## 11.3 Create request mapping

The page calls `createSalesQuotation(sqData)` with:

- `party_id` from the transaction payload.
- `warehouse_id` from the transaction payload.
- `quotation_date` from the transaction date or today.
- `valid_until` from the expected-delivery date or null.
- `remarks` from transaction notes.
- `revised_from_id`.
- `lines`, mapped as:
  - `item_id`
  - `variant_id`, or null
  - `uom_id`, or null
  - `batch_id`, or null
  - `quantity`
  - `unit_price`
  - `unit_discount`, or zero
  - `tax_rate: 0`
  - `remarks: null`
  - `is_free_qty`
  - `parent_line_uids`
  - `uid`

Although the shared transaction payload can carry other properties, this page’s shown mapping does not forward payments, expenses, supplier reference, currency fields, line discount percentage, or the displayed transaction totals.

## 11.4 Status and deletion calls

The page’s action handlers call:

- `sendSalesQuotation(id)`
- `acceptSalesQuotation(id)`
- `rejectSalesQuotation(id)`
- `cancelSalesQuotation(id)`
- `deleteSalesQuotation(id)`
- `convertQuotationToOrder(id)`

Successful send, accept, reject, and cancel operations refresh the list and update the detail view if the same quotation is open. Successful deletion refreshes the list. Conversion success closes the detail view and refreshes the list.

## 11.5 Backend response resource fields

The supplied quotation resource can return these quotation-level values:

- ID and entity ID.
- Organization ID.
- Quotation number and revision number.
- Quotation date and validity date.
- Subtotal, tax amount, discount amount, and grand total.
- Status.
- Terms and conditions and remarks.
- Party and warehouse IDs.
- Expired state and source revision ID.
- Created and updated timestamps.
- Loaded customer information under the resource key `party`.
- Loaded warehouse information.
- Loaded lines.
- Converted Sales Order information when present and loaded.

Line resources can return:

- Line, quotation, item, variant, and unit IDs.
- Quantity, unit price, unit discount, tax rate, and subtotal.
- Free-quantity state and parent-line IDs exposed as `parent_line_uids`.
- Remarks.
- Loaded item, variant, unit, and batch data.

**Response-shape note:** the supplied UI reads `customer` in list rows and details, while the supplied resource constructs its customer-like object under the key `party`. The provided excerpts do not show any client-side normalization between these names, so the exact runtime presentation depends on any unprovided API-client transformation.

The service’s list query loads customer data for list results and orders results newest-created first. The detail query loads customer, warehouse, line-related item/variant/unit/batch data, and converted Sales Order information.

---

# 12. Backend validations and business rules

## 12.1 Request validation for creating quotations

The supplied `StoreSalesQuotationRequest` rules require:

- `party_id`
  - Required.
  - Integer.
  - Must identify an existing party.

- `warehouse_id`
  - Nullable.
  - If supplied, integer.
  - Must identify a warehouse belonging to the organization resolved from the `X-Organization-Id` header or request `organization_id`.

- `revised_from_id`
  - Nullable.
  - If supplied, integer.
  - Must identify a quotation belonging to that organization.

- `quotation_date`
  - Required.
  - Must be a date.

- `valid_until`
  - Nullable.
  - If supplied, must be a date on or after `quotation_date`.

- `terms_and_conditions`
  - Nullable string.

- `remarks`
  - Nullable string.

- `lines`
  - Required array.
  - Must contain at least one line.

For each line:

- `item_id`: required integer and must identify an existing item.
- `variant_id`: nullable integer and, if supplied, must identify an existing variant.
- `quantity`: required numeric value with minimum `0.0001`.
- `unit_price`: required numeric value with minimum `0`.
- `unit_discount`: nullable numeric value with minimum `0`.
- `tax_rate`: nullable numeric value from `0` through `100`.
- `remarks`: nullable string.
- `uom_id`: nullable integer and, if supplied, must identify an existing unit of measure.
- `batch_id`: nullable integer and, if supplied, must identify an existing batch.
- `is_free_qty`: nullable boolean.
- `parent_line_uids`: nullable array.
- `uid`: nullable string.

The supplied rules do not state a maximum quotation quantity, maximum unit price, or maximum discount value.

## 12.2 Additional item/variant validation

After ordinary validation, the request checks each line’s item in the resolved organization:

- If the item has variants and the line does not provide a variant ID, validation adds:
  - **Variant is required for this item.**
- If a variant is supplied and it belongs to a different item, validation adds:
  - **The selected variant does not belong to the selected item.**

## 12.3 Organization context

The controller resolves the organization from:

1. `X-Organization-Id` header.
2. Request `organization_id`.
3. The authenticated user’s first organization.

The list and create controller methods return an error if no organization context is available. List, detail, status-action, delete, and conversion service lookups are scoped to the resolved organization.

## 12.4 Server-side total and free-line calculations

On create, the service calculates quotation totals from submitted lines:

- A free-quantity line has unit price, unit discount, and tax rate set to zero.
- Per-line total discount is quantity multiplied by unit discount.
- Per-line subtotal is quantity multiplied by unit price, less that total discount.
- Per-line tax is line subtotal multiplied by tax rate divided by 100.
- Quotation subtotal, tax amount, and discount amount are accumulated from lines.
- Grand total is subtotal plus tax amount.
- Stored calculated monetary totals are rounded to two decimal places.
- A free-quantity line’s parent UIDs are mapped to created quotation-line IDs when matching UIDs exist.

The UI sends `tax_rate: 0` for every line in its create mapping. The backend request accepts a tax rate, but this page’s shown submit mapping does not submit a nonzero one.

## 12.5 Status-transition rules

The supplied service enforces these rules:

- **Send:** only a draft quotation can be sent.
  - Otherwise: **Only draft quotations can be sent.**
- **Accept:** only a sent quotation can be accepted.
  - Otherwise: **Only sent quotations can be accepted.**
- **Reject:** only a sent quotation can be rejected.
  - Otherwise: **Only sent quotations can be rejected.**
- **Cancel:** converted quotations cannot be cancelled.
  - Otherwise: **Cannot cancel a converted quotation.**
  - The service code shown does not impose another status restriction on cancellation.
- **Convert:** only an accepted quotation can be converted.
  - Otherwise: **Only accepted quotations can be converted to sales orders.**
- **Update:** only draft quotations can be edited through the update service.
  - Otherwise: **Only draft quotations can be edited.**
  - The page does not expose that update operation as a list or detail action in the supplied UI.
- **Delete:** a quotation that already has a converted Sales Order cannot be deleted.
  - Otherwise: **Cannot delete a quotation that has been converted to a sales order.**
  - The service does not show a draft-only deletion rule, though the UI only displays Delete for draft rows.

## 12.6 Expiration behavior

The model derives `is_expired` from whether a non-null `valid_until` date is in the past. The detail UI uses the returned `is_expired` value to show **(EXPIRED)** in red. The supplied UI does not show a dedicated expire action.

## 12.7 UI-only behaviors versus backend constraints

These behaviors are from the shared UI and should not be confused with the request validation rules:

- The percentage discount entry clamps to 0–100 in the UI; the request rules shown validate `unit_discount`, not a percentage field.
- The amount discount entry is capped at the line’s unit price in the UI.
- Quantity entry is clamped to at least zero in the update handler and the input has `min={0.001}`; the backend request requires at least `0.0001`.
- The shared screen can require selected batches or serial numbers based on item tracking and configuration. The quotation-specific submit path shown always performs the batch quantity-match check for batch-tracked Sales/quotation lines. Its serial selection behavior depends on the tracking configuration.
- The backend request requires at least one line and validates line quantity, price, discount, tax, and references independently of those UI controls.

The supplied backend excerpts do not provide detailed stock-conversion validation rules or the conditions that produce `INSUFFICIENT_STOCK`; the UI only shows how it presents the returned shortage data.

---

# 13. Explicit scope notes

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

The quotation screen can display item, variant, unit, batch, and stock information through shared transaction and resource components. That does not make the underlying Inventory, Core, or Finance management screens part of this quotations page.

## Confidence

---

## Feature: REPORTS

# Sales Reports

## 1. Global navigation and entry flow

The global menu lists this page as:

- **Sidebar label:** Sales Reports
- **Menu group:** Analytics
- **Route:** `/sales/reports`
- **Module:** Sales
- **Permission:** `null` in the supplied menu entry

The page source is `apps/common-ui/sales-ui/app/reports/page.tsx`. The supplied global menu identifies **Sales Reports** as a Sales sidebar item. No links or navigation actions to other pages appear in this page’s component.

## 2. Overview

This page is a placeholder for future sales analytics. It displays a page title, a short description, and a “Coming Soon” message describing report types that are planned for a future update.

The component does not display reports, charts, dashboards, filters, or report data.

## 3. Sub-pages and routes

There is **one page** in the supplied code:

- **Sales Reports:** `/sales/reports`

No nested routes, tabs, or additional screens are defined in the supplied component.

## 4. UI layout and elements

The component renders the following elements, in this order:

1. **Page heading**
   - Text: **Sales Reports**
   - Rendered as an `<h1>`.

2. **Page description**
   - Text: **Sales analytics, revenue dashboards, and performance metrics.**
   - Rendered as a paragraph beneath the heading.

3. **Content area**
   - A containing `<div>` holds a centered-looking inner content block, based on the presence of styling classes whose actual values are abbreviated as `"..."` in the supplied code. The exact visual alignment, dimensions, colors, and spacing cannot be determined from the provided source.

4. **Icon**
   - Text/emoji: **📊**

5. **Placeholder heading**
   - Text: **Coming Soon**
   - Rendered as an `<h2>`.

6. **Placeholder description**
   - Exact text: **Sales dashboards with revenue by customer, by item, by period analysis, AR aging reports, and POS summary will be available in a future update.**

### Elements not present in the supplied component

There are no visible:

- Report cards or report results
- Charts or tables
- Search, filter, date-range, or sorting controls
- Form inputs
- Buttons or links
- Modals or dialogs
- Loading, error, empty-data, or permission-denied screens
- Conditional content states
- Sales transaction or product-entry components

**CRITICAL NOTE**: This is a view-only page. Users cannot manually create a reports here.

## 5. Step-by-step user experience

1. The user opens **Sales Reports** from the Sales menu at `/sales/reports`.
2. The page displays the **Sales Reports** heading.
3. Beneath it, the page displays the description: “Sales analytics, revenue dashboards, and performance metrics.”
4. The content area displays the 📊 icon and the **Coming Soon** heading.
5. The page explains that dashboards and analyses for revenue by customer, by item, by period, AR aging, and POS summary are planned for a future update.
6. No further action is available on the page in the supplied code: it has no controls, forms, or links.

## 6. API and data flow

The supplied component does not make an API request, import an API client, or read or submit report data. Its rendered content is static text and an emoji.

No interactions connect this page to sales orders, invoices, POS, customers, or other Sales UI pages in the provided code. The referenced report categories are mentioned only in the placeholder text; the code does not implement those reports or show how their data would be obtained.

## 7. Conditional rendering and states

The page component returns the same content unconditionally. No conditional branches, state variables, event handlers, or alternate screens appear in the supplied source. Accordingly, the code does not define different states for loading, populated reports, errors, or user actions.

## 8. Backend validations and business rules

No backend validation rules or business logic are included in the provided page code. No extracted backend validations were supplied with the code, so none can be documented from this material.

The UI contains no discount controls, transaction fields, or other inputs to which validation rules could apply. No `ProductTransactionScreen` is used.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---

## Feature: POS

# POS feature guide

## 1. Global navigation and entry flow

The supplied Sales menu lists these POS links:

- **POS Sales** — `/sales/pos` — Sales menu, POS group.
- **Terminal Sessions** — `/sales/pos/sessions` — Sales menu, POS group.

The code also contains terminal administration and checkout screens that are not listed as Sales menu entries:

- The terminal-management component is in `app/pos/terminals/page.tsx`. It is **not listed in the supplied menu**, so it is a hidden/internal route rather than a documented sidebar destination.
- The checkout component is in `app/pos/create/page.tsx`. POS Sales links to it using `href="/pos/create"`. It is **not listed in the supplied menu**, so it is a hidden/internal route reached through the **New Sale** link, not a sidebar destination.
- The checkout screen labels itself **POS Terminal**. That title does not establish a sidebar link; the menu lists **POS Sales**, not “POS Terminal.”

The POS Sales list also links to `/returns/create?source_type=pos_sale&document_id=…&auto_fetch=true` when a user chooses **Process Return**. That destination is not listed as a Sales menu entry in the supplied menu. The menu’s listed Sales Returns destination is `/sales/returns`; do not treat the action’s URL as a listed sidebar route.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---

## 2. Overview

The supplied code covers four connected POS experiences:

1. **POS Sales history** — search, filter, paginate, inspect, and print completed POS sales; initiate a return through a linked route.
2. **Terminal Sessions** — inspect session history, filter it, view session details, and—when the UI’s permission conditions are met—close an open session.
3. **Terminal management** — list, search, create, edit, and delete POS terminal stations. This screen is not in the supplied sidebar menu.
4. **POS checkout** — open or restore a terminal session, build a sale through the shared product-transaction interface, submit checkout, handle stock-shortage responses, print a receipt, and close the session. This screen is not in the supplied sidebar menu; POS Sales reaches it through **New Sale**.

The code distinguishes between the sales-history list and the checkout form: POS sales are created through the checkout flow, not by editing a row in the history list.

---

# 3. POS Sales history

**Menu entry:** Sales → **POS Sales**  
**Route:** `/sales/pos`

## 3.1 Page header and controls

The page header displays:

- **POS Sales**
- A record count, shown when the list is not loading.
- The description: **“Point of Sale transactions history.”**

The page exposes responsive search/filter controls:

- A mobile-options control with:
  - Search label: **“Search POS Sales”**
  - Search placeholder: **“Search by POS #, GIN #...”**
  - A **Filters** dropdown item that toggles the filter panel.
- A desktop **Filters** button, which also toggles the filter panel.
  - It receives an active style when the panel is open or date/customer filters are set.
  - A dot indicator is shown when date/customer filters are active.
- A desktop search popover with placeholder **“Search by POS #, GIN #...”**.
- A **New Sale** link with a plus icon. It navigates to `/pos/create`, the checkout screen described later.

Search waits 500 ms after typing before updating the debounced term. When that term updates, the page resets to page 1.

## 3.2 Filter panel

The panel is shown only after toggling **Filters**. It contains:

- **Date From** — date input.
- **Date To** — date input.
- **Customer** — `PartyPicker` configured with:
  - Label: **“Customer”**
  - Party type: **customer**
- **Clear All** — shown only when at least one of the date or customer filters is active. It clears both dates, the selected customer ID and name, the search field, and resets to page 1.

Changing a date or customer resets the page to page 1. The filter request includes only values that are set.

## 3.3 Sales table

The table has ten columns:

1. **POS #**
2. **GIN #**
3. **Customer**
4. **Terminal**
5. **Grand Total**
6. **Payment**
7. **Cashier**
8. **Date**
9. **Status**
10. **Actions**

While loading, a ten-column loader is rendered. When there are no results, the empty-state text is:

- **“No POS sales match your filters.”** if a customer/date filter or search term is present.
- **“No POS sales found.”** otherwise.

Each sale row displays:

- **POS #** — shopping-cart icon and `pos_number`.
- **GIN #** — `gin.gin_number`, or `-`.
- **Customer** — `party.name`, or `-`.
- **Terminal** — terminal name, then terminal code as fallback, or `-`.
- **Grand Total** — formatted to two decimal places.
- **Payment**:
  - `-` when `grand_total` is zero.
  - Otherwise, a payment-method icon and payment-method text. Cash gets a banknote icon; card and the default case use a card icon; multiple uses a wallet icon.
- **Cashier** — cashier name, or `-`.
- **Date** — localized date from `created_at`, or `-`.
- **Status** — a badge showing the status text. `completed` uses the success color; other statuses use the warning color.

Clicking a row opens **POS Sale Details**. The Actions cell stops the row click from firing and provides a dropdown with:

- **View Details** — opens the same detail view.
- **Process Return** — navigates to `/returns/create` with `source_type=pos_sale`, the sale’s `document_id`, and `auto_fetch=true`.

Pagination appears when the page is not loading and the reported total is greater than 15. It uses 15 records per page.

## 3.4 POS Sale Details modal

The modal title is **“POS Sale Details”** and its size is `lg`. It opens as soon as a row is clicked, initially displaying the row’s sale data while the detail request is loading. If the request succeeds, the modal data is replaced with the fetched detail. The code does not render a separate detail-loading indicator.

### Sale heading and actions

The top section shows:

- The POS number.
- `GIN: ` followed by the GIN number, or `-`.
- The party name after a bullet, if present.
- A **Print** button.
- A status badge displaying the sale status. In this modal the badge is assigned the success color regardless of the status text.

Clicking **Print** opens the print selector described below.

### Summary fields

The summary section displays:

- **Terminal** — terminal name, then terminal code, or `-`.
- **Cashier** — cashier name, or `-`.
- **Payment** — `-` for zero grand total; otherwise payment icon and method, with `-` as the method fallback.
- **Date** — localized date and time from `created_at`, or `-`.

### Invoice section, when present

If `viewingSale.invoice` exists, the modal displays:

- **Invoice #** — invoice number.
- **Invoice Status** — status badge. `paid` uses the success color; all other statuses use the warning color.

### Items section, when GIN lines are present

The **Items** table appears only if `viewingSale.gin.lines` exists and contains at least one line. Its columns are:

- **Item**
- **Qty**
- **Unit Price**
- **Unit Disc**
- **Total**

The item cell can include:

- The item name, or **“Deleted Item (ID: …)”** when the item relation is missing.
- The variant name in parentheses when a variant exists and the item has variants, or when the variant name is not `Default`.
- A **Free** badge when the line is free quantity.
- For a free line with parent line IDs, a **“For: …”** line:
  - Parent item name and, where applicable, variant name.
  - `#<id>` if the referenced parent line or item is unavailable.
- **“Batch: …”** when batch information exists.
- **“SN: …”** when serial-number information exists.

The quantity is the numeric dispatch quantity, followed by the unit-of-measure abbreviation when available. Unit price, unit discount, and line subtotal are formatted to two decimal places.

### Payment History section, when invoice payments exist

The **Payment History** table appears only when the invoice has a nonempty `payments` list. Its columns are:

- **Date** — localized payment date, or `-`.
- **Method** — payment icon and method text, or `-`.
- **Reference** — payment reference, or `-`.
- **Amount** — formatted payment amount.

### Totals

The modal always displays:

- **Subtotal**
- **Discount** only when the discount amount is greater than zero; it is displayed as a negative amount.
- **Tax** only when the tax amount is greater than zero.
- **Grand Total**

Amounts are formatted to two decimal places.

### Modal action

A **Close** button dismisses the details modal.

## 3.5 Print selector data

The details modal passes a `TransactionPrintSelector` these settings:

- `transactionType="sales"`
- `entityId={null}`
- `autoPrintTemplateId` from the loaded Sales setting `pos_receipt_template_id`, converted to a number when present.

When a sale is available, it supplies a one-entry `batchEntitiesData` array containing the sale and mapped receipt fields. Item rows are mapped with:

- A two-digit sequential **index**.
- **description**: item name or `Unknown`, with a non-default variant name in parentheses.
- **qty**: dispatch quantity, falling back to `qty` or `quantity`.
- **unit_price**
- **unit_discount**
- **amount**: line subtotal, falling back to `subtotal`.

The supplied sale-level print values include:

- **sale_number** from the POS number.
- **payment_method**, with `Credit (settled)` when the sale is credit and the invoice is paid; otherwise an underscore-separated method is title-cased, with `Cash` as fallback.
- **amount_paid**, **amount_tendered**, **total_paid**, **balance_due**, **tax**, and **change_due**, calculated from the sale and invoice fields in the code.
- **sale_date** and **sale_time** from `created_at`.
- **creator** from the cashier.
- **customer** from the party.

---

# 4. Terminal Sessions

**Menu entry:** Sales → **Terminal Sessions**  
**Route:** `/sales/pos/sessions`

**CRITICAL NOTE**: This is a view-only page. Users cannot manually create a pos here.

This page has no session-creation control. It does, however, provide a conditional **Close Session** action for eligible open sessions.

## 4.1 Header and search

The header displays:

- **Terminal Sessions**
- A record count when not loading.
- **“POS session history — opening/closing balances and reconciliation.”**

Responsive search controls include:

- Mobile search label **“Search Sessions”** and placeholder **“Search...”**.
- A mobile **Filters** dropdown item.
- A desktop **Filters** button, with active styling and a dot when filters are active.
- A desktop search popover with placeholder **“Search terminal, user...”**.

Search is debounced by 500 ms and resets pagination to page 1.

## 4.2 Filter panel

When open, the filter panel contains:

- **Date From** — date input.
- **Date To** — date input.
- **Terminal** — select:
  - **All Terminals** for the empty value.
  - One option per loaded terminal, displayed as `terminal_code — name`.
- **Status** — select:
  - **All Statuses**
  - **Open**
  - **Closed**
- **Clear All** — shown when any date, terminal, or status filter is active. It clears those filters and resets to page 1. It does not clear the search term.

The page loads terminals using `getTerminals({ per_page: 1000 })` to populate the Terminal selector. A filter change resets pagination to page 1.

## 4.3 Sessions table

The table headings are:

1. **Terminal**
2. **User**
3. **Opened At**
4. **Closed At**
5. **Duration**
6. **Opening**
7. **Expected**
8. **Actual**
9. **Difference**
10. **Notes**
11. **Status**
12. An unlabeled actions column

While loading, the component uses `TLoader` with `cols={11}`. The empty state says **“No terminal sessions found.”** Pagination appears when not loading and at least one session is present; page size is 15.

Each row is clickable and opens **Session Details**. It displays:

- **Terminal** — terminal code, or `-`.
- **User** — user name, or `-`.
- **Opened** — localized date and time, or `-`.
- **Closed** — localized date and time, or `-`.
- **Duration** — elapsed time from opening to closing, or to the current time for an open session. It is shown as hours and minutes when at least one hour has elapsed, otherwise minutes.
- **Opening** — opening balance formatted to two decimal places.
- **Expected** — expected closing balance when truthy; otherwise `-`.
- **Actual** — actual closing balance when truthy; otherwise `-`.
- **Difference**:
  - For closed sessions, a signed, two-decimal difference when its absolute value is greater than `0.01`.
  - A zero-style formatted value without a sign when the absolute difference is at most `0.01`.
  - `-` for open sessions.
  - A positive difference is styled green; a negative difference red; a difference within the threshold gray.
- **Notes** — closing notes with a message icon and the full note as the title attribute, or `-`.
- **Status** — status badge. `open` uses the success color and includes a small indicator; other statuses use the default color.

## 4.4 Conditional session actions

An actions dropdown is rendered only when both conditions are true:

1. The session status is `open`.
2. The current user is the session’s user, **or** `can("pos_session.close_any")` returns true.

The dropdown contains **Close Session**. Choosing it:

- Closes the dropdown.
- Sets the selected session as the session to close.
- Initially uses that session’s row data in the close modal.
- Requests the first open session for the same terminal and, if returned, refreshes the modal data with that result.

**Code-level distinction:** The UI can expose the close action to a user with `pos_session.close_any`, but the supplied backend close service scopes its lookup to the authenticated user’s own open session. The provided code therefore does not show the backend honoring cross-user closure merely because the UI permission allows the action.

## 4.5 Close Terminal Session modal

This modal is rendered when both the session-to-close and modal session data are present. Its title is **“Close Terminal Session”**, size `md`.

It displays these summary values:

- **Opening Balance**
- **Expected Closing Balance**
- **Session Duration** — opening time followed by `— Now`, or `-` if there is no opening time.

The form contains:

- **Actual Closing Balance** — required numeric input, placeholder **“Count and enter actual cash...”**, `step="0.01"`, `min={0}`.
- A live difference summary after an actual balance value is entered:
  - **“Balance matches — no difference”** when the absolute difference is at most `0.01`.
  - Otherwise **“Difference: …”**, with a leading plus for a positive difference.
  - The accompanying text says **“Surplus detected”** or **“Shortage detected”**, followed by **“— please provide a note below.”**
- **Notes** — a required textarea shown only when the difference exceeds the `0.01` threshold. It has placeholder **“Explain the difference...”** and three rows.

Actions:

- **Cancel** — disabled while submitting; closes the modal otherwise.
- **Close Session** — submits the values and shows a loading state while the request is in progress.

UI submission checks:

- An empty or nonnumeric actual balance triggers the toast **“Please enter the actual closing balance”**.
- If the difference exceeds `0.01`, blank/whitespace-only notes trigger **“Please enter a note explaining the difference”**.
- The UI submits `actual_closing_balance` and `closing_notes`. Although the callback type permits `handover_to`, this modal provides no handover input and does not submit that field.

On success, the page shows **“Session closed successfully!”**, clears the close-modal state, and refreshes the session list. Failures show the returned message or **“Failed to close session”**.

## 4.6 Session Details modal

Clicking a row opens a **Session Details** modal, size `lg`.

It displays:

### Terminal heading

- Terminal code, or **“Unknown Terminal”**.
- Terminal name, or **“Terminal”**.
- Status badge, with a small indicator for open sessions.

### Cashier and duration

- **Cashier** — user name, or `-`.
- **Duration** — elapsed duration using the same hours/minutes formatting as the table.
- A date-time range: opened timestamp, then `—`, then closed timestamp or **“Now”**.

### Balances

- **Opening Balance**
- **Expected Closing Balance** — formatted unless the value is `null`, in which case `-`.
- For closed sessions only:
  - **Actual Closing Balance**

### Closed-session difference panel

Only for closed sessions:

- A difference greater than `0.01` displays **“Difference: …”**, with a plus sign for a surplus, and then **“Surplus”** or **“Shortage.”**
- A difference within the threshold displays **“Balance matches — no difference.”**

### Closing notes and action

- **Closing Notes** appears only when notes exist.
- **Close** dismisses the modal.

---

# 5. Terminal management

**Source:** `app/pos/terminals/page.tsx`  
**Menu status:** Not listed in the supplied Sales menu; this is a hidden/internal screen, not a documented sidebar destination.

## 5.1 Header, search, and create controls

The header displays:

- **Terminal Master**
- A record count when not loading.
- **“Manage POS terminal stations for your organization.”**

Search controls include:

- Mobile search label **“Search Terminals”**.
- Placeholder **“Search by code or name...”**.
- Desktop search popover with the same placeholder.
- Search is debounced 500 ms and resets to page 1.

The page has two ways to open terminal creation:

- Mobile dropdown item **Add Terminal**.
- Desktop **Add Terminal** button.

Opening creation clears edit state and initializes:

- Terminal code: empty.
- Name: empty.
- Warehouse ID and display name: empty.
- Status: `"1"` (Active).

## 5.2 Terminal table

Columns:

1. **Terminal Code**
2. **Name**
3. **Warehouse**
4. **Status**
5. **Actions**

While loading, a five-column loader is shown. Empty-state messages are:

- **“No terminals found matching your criteria.”** when the search term is set.
- **“No terminals found. Create your first POS terminal.”** otherwise.

Rows show:

- **Terminal Code** — monitor icon and code.
- **Name**
- **Warehouse** — warehouse name, then code, or `-`.
- **Status** — **Active** or **Inactive** badge.
- **Actions** dropdown:
  - **Edit Terminal**
  - **Delete Terminal**, with confirmation.

Pagination appears when not loading and there is at least one terminal. Page size is 15.

## 5.3 Add New Terminal modal

The create modal title is **“Add New Terminal”**, size `md`. Its fields are:

- **Terminal Code** — required; placeholder **“e.g. POS-01”**.
- **Name** — required; placeholder **“e.g. Main Counter”**.
- **Warehouse** — `WarehousePicker`, required.
- **Status** — select with **Active** and **Inactive** options.

Actions:

- **Cancel** — closes the modal and clears edit state.
- **Create Terminal** — submits the form.

The submitted payload contains terminal code, name, warehouse ID (numeric or `null`), and a boolean `is_active`. It does not contain a description field.

## 5.4 Edit Terminal modal

Choosing **Edit Terminal** fills the same form with the selected terminal’s:

- Code.
- Name.
- Warehouse ID and warehouse name.
- Active/inactive status.

The edit modal title is **“Edit Terminal”**, size `md`. Its form has the same fields and **Cancel** action as creation; the submit button reads **“Update Terminal.”**

On successful create or update, a success toast uses the server message or a created/updated fallback, closes the form, and refreshes the list. A failed response shows its message or **“Failed to save”**; a thrown error shows its message or **“An error occurred.”**

## 5.5 Delete confirmation

The action dropdown’s **Delete Terminal** item opens a confirmation with:

- Title: **“Delete Terminal”**
- Body: **`Are you sure you want to delete "<terminal_code> — <name>"? This action cannot be undone.`**

Confirming calls the delete operation, then closes the confirmation. On success the page shows **“Terminal deleted”** and refreshes the list. Failed responses and exceptions show the supplied message or a failure fallback.

---

# 6. POS checkout and terminal screen

**Source:** `app/pos/create/page.tsx`  
**Entry:** POS Sales → **New Sale**  
**Linked URL:** `/pos/create`  
**Menu status:** Not listed in the supplied Sales menu; this is a hidden/internal route reached through the POS Sales page.

## 6.1 Session restoration and initial screen

On entry, the screen first renders **“Restoring session...”** with a loading icon while it calls the active-session API.

- If an active session is returned, the page restores its terminal, terminal information, opening balance, and session state, and writes the session to local storage under `pos_active_session`.
- If no active session is returned, a stored session with an ID and `open` status is cleared from local storage.
- The page separately loads active terminals using `is_active: 1` and `per_page: 100`, and loads Sales settings.

When restoration finishes and there is no active session, the page returns the **Open POS Session** screen rather than the transaction form.

## 6.2 Open POS Session screen

The screen heading and explanatory text are:

- **“Open POS Session”**
- **“Select a terminal and enter opening cash balance to begin”**

A top-right **Close** icon calls `router.push('/delivery-notes')`.

### Terminal loading state

While terminal data is loading, the screen displays:

- A loading icon.
- **“Loading terminals...”**

### Empty-terminal state

If no terminals are available, it displays:

- **“No Terminals Found”**
- **“Please create a POS terminal in Terminal Master before starting a session.”**

No start button is rendered in this state.

### Terminal selection

When terminals exist, the screen displays the required label **Terminal** and one button per terminal. Each button shows:

- `terminal_code — name`
- Warehouse name or warehouse code when a warehouse exists.
- **“In Use”** when `has_active_session` is true.
- A selected-state check indicator when selected.

A terminal with an active session is disabled. Selecting an available terminal clears the terminal-selection error.

### Opening balance

The required **Opening Cash Balance** input is numeric, uses placeholder **“0.00”**, has `step="0.01"`, `min={0}`, and receives autofocus. Entering a value clears the balance error.

UI validation on **Start Session**:

- No selected terminal: **“Please select a terminal”**.
- Empty, nonnumeric, or negative opening balance: **“Please enter a valid opening balance”**.

The **Start Session** button is disabled when no terminal is selected or a submission is in progress. During submission its text is **“Opening Session...”**; otherwise it is **“Start Session.”** Pressing Enter in the balance input calls the same confirmation handler when a terminal and balance are present.

On a successful open request, the screen saves the returned session, marks it active, and shows **“Session started!”**. On failure it displays the returned message or **“Failed to open session.”**

## 6.3 Active POS screen header

With an active session, the page shows:

- A back button that calls `router.back()`.
- **“POS Terminal”**
- **“Process sales and generate receipts”**
- A terminal indicator showing terminal code, or `#<terminal ID>`, followed by `— <name>` when a name exists.
- **Close Session**
- A fullscreen toggle:
  - **Fullscreen** title while not fullscreen.
  - **Exit Fullscreen** title while fullscreen.

Fullscreen preference is saved and restored using the `pos_fullscreen` local-storage setting.

## 6.4 ProductTransactionScreen: product entry and line editing

The active POS screen injects the shared `<ProductTransactionScreen>` with:

- `TRANSACTION_PRESETS.pos`
- `enableSalesUnit` from the loaded Sales setting.
- The selected terminal’s warehouse ID as the default warehouse.
- The POS checkout submit handler.
- The fullscreen state.

The supplied code does not include the contents of `TRANSACTION_PRESETS.pos`, so preset-dependent controls cannot be asserted unconditionally. The shared component’s fields and behaviors below are documented as written, including their configuration conditions.

### Product search

Unless `config.disableItemSelection` is true, the product panel contains a search input with:

- Placeholder **“Search by name, SKU, or scan barcode...”**
- Or, when a warehouse is required but not selected: **“Select a warehouse first to search items...”**
- Search disabled when a warehouse is required but missing.
- A loading indicator while searching.
- An auto-add toggle with the hint: **“Automatically adds an item to the list when a barcode is scanned or an exact match is found.”**
- An optional plus button titled **“Create new item”** only when an `onAddNewItem` callback is supplied. This POS page does not supply that callback.

Search starts after 250 ms. The request includes the search text, limit 20, and transaction type. It includes warehouse ID when available; POS/sales/quotation searches also request sales prices and include transaction type and party ID when selected.

When an exact match is returned and auto-add is enabled, the code handles serial, batch, variant, and item matches differently:

- A serial match adds the item with the matched serial and quantity 1.
- A batch match in POS adds the item with that batch and quantity 1.
- A variant or item match selects the corresponding item/variant.
- Otherwise search results are displayed.

Results can display:

- Item image or a package icon.
- Item name and SKU.
- Variant count badge.
- Price when `config.showPrices` is enabled.
- Available stock when `config.showStock`, the item has stock, and stock data exists.
- Expanded variant rows, with variant name, SKU, price, and available stock.
- **“No active variants found.”** when an expanded variant-bearing item has no variants.
- **“No items found for "<search>"”** when a completed search has no results.

Keyboard behavior in an open result list:

- Arrow Up/Down moves the focused result.
- Enter selects a result or expands an item with variants, depending on selection configuration.
- Escape closes the result list.

### Empty cart and item table

With no line items, the panel displays:

- **“No items added”**
- **“Search for products above to add them”**

With items, the table shows:

- **Item**
- **Qty**
- **Unit**, only when purchase or sales units are enabled.
- **Rate**, when prices are shown.
- **Disc.**, when prices are shown and the transaction type is sales, quotation, or POS.
- **Total**, when prices are shown.
- An unlabeled remove-action column.

The item cell can show an image or package icon, item name, **Free** marker, SKU, and variant name/SKU. Depending on `allowItemLevelSelection`, a variant-bearing item may show **“Any Variant”** or a **Select variant…** dropdown. That dropdown has one option per variant, displayed as `variant_name — sku`.

### Batch and serial controls

The batch/serial controls are conditional on item tracking and configuration:

- POS batch-tracked lines show a batch selector with placeholder **“Select Batch...”**. It loads batches for the item and optional variant/warehouse, and displays batch number and available stock when a warehouse is selected. Selecting a batch sets the line’s batch and selling price; clearing it removes the batch.
- For batch-tracked lines where the panel uses the batch-selection modal, the control can show **“Select Batches”**, selected counts, mismatch warnings, or a selected-batches checkmark. The modal is passed `allowMultiple={true}`, the warehouse, and the configured create permission. The modal’s internal fields are not included in the supplied code.
- Serial-tracked lines can show **“Select Serial Numbers”**, selected counts, mismatch warnings, or a selected-serials checkmark. The modal receives the item, variant, warehouse, configured create permission, and initial selections. Its internal fields are not included in the supplied code.
- Batch selection is disabled while a required variant is unresolved. Serial selection is likewise disabled while a required variant is unresolved.
- At submit, batch and serial selections are validated under the rules described in the validation section below.

### Free quantity and parent line

A **Free Quantity** checkbox is shown for zero-priced items in the listed transaction types, including POS. It is disabled when the line is linked to a purchase-order, sales-order, or quotation line.

When checked:

- The line’s unit price, discount, and total are set to zero.
- A **Select Parent Line...** control appears.
- The parent selector is disabled when the same linked-line condition applies.
- Its hint says: **“Select the original line item that this free quantity is associated with.”**

When an eligible parent is chosen, the display can show that parent’s item and variant or the number of selected parents. The supplied `ParentLineSelectionModal` usage identifies the selectable lines but does not include that modal’s inner UI fields.

### Quantity, unit, rate, discount, and row actions

- **Qty** is a numeric input with `min={0.001}` and `step="any"`. The client-side update logic clamps edited quantity to at least zero.
- **Unit** is a selector of the item’s unit-of-measure options, when the unit column is enabled. It is disabled for serial-tracked lines and pending POS batch lines.
- **Rate** is a text input accepting digits and up to two decimal places. It is disabled when price editing is disallowed, the line is free, or a POS batch-tracked line has no batch selected.
- **Disc.** contains:
  - A dropdown with **Amt** and **%**.
  - A numeric discount input with placeholder **“0.00”**, `min={0}`, and `step="any"`.
  - The exact disabled conditions are listed separately below.
- **Total** displays the line total formatted to two decimal places.
- The remove button has title **“Remove Item”**. Removing a parent also removes its UID from the parent references on other lines.

The footer reports the number of line items and the sum of quantities adjusted by each unit’s conversion factor, displayed as `items · units`. When prices are enabled, it also displays the summed line total.

### POS subtotal and amount-to-pay card

For POS only, when there is at least one line, the shared screen displays:

- **Subtotal**
- **Discount**, only when the discount total is positive
- **Amount to Pay**

The grand amount is calculated in the shared UI as subtotal minus discount total. The supplied POS wrapper maps each line’s tax rate as `0`, so the checkout payload from this screen does not send a nonzero tax rate.

## 6.5 MetadataPanel fields and payment area

The shared transaction component renders `MetadataPanel`. Which fields appear depends on its configuration.

### Party

When party display is enabled:

- POS uses a `PartyPicker` unless configured as a warehouse party.
- Its configured party label is used.
- The picker is not marked required for POS (`config.type !== 'pos'` is false).
- It is disabled when party selection is disabled in configuration.

Selecting a party can trigger price-list evaluation when the party changes and lines already exist. Currency behavior is conditional on currency support in configuration.

### Warehouse

When `config.showWarehouse` is true, a required **Warehouse** picker appears. It is disabled when warehouse selection is disabled by configuration. The POS wrapper separately supplies the selected terminal’s warehouse as the default warehouse.

### Conditional currency fields

When currency is enabled and the associated callbacks exist:

- A currency picker is shown.
- If the selected currency differs from the base currency, an **Exchange Rate** input appears with the displayed relationship `1 <currency code> = <input> <base currency code>`.
- The input has `min="0.000001"` and `step="0.000001"`.

### Date and other metadata

The component can render these fields when enabled and supplied with their callbacks:

- **Date** — date input.
- Expected delivery date — configurable label, defaulting to **“Expected Delivery”**.
- **Supplier Invoice No / Ref** — text input with placeholder **“e.g. INV-2023-001”**.
- **Notes** — textarea with placeholder **“Add transaction notes...”**, two rows.
- **Other Expenses (Couriers, Labor, etc.)** — opens an Other Expenses modal, with an item-count badge when expenses exist. The modal’s internal fields are not included in the supplied code.

The shared POS page supplies transaction date, notes, payments, and other component props, but the exact preset flags determine which conditional fields are actually shown. The supplied preset object is not included.

### Payment section

When `config.showPayment` is true:

- A **Payment** section renders `PaymentSection`.
- Payment modes and bank account lookups are loaded.
- The payment section is passed the total amount, existing payment entries, payment-mode and bank-account loaders, and `compact={true}`.
- `collapseModes` is true for POS.
- The supplied code does not include the internals of `PaymentSection`, so it does not establish a specific set of payment-mode toggle labels or mode-specific controls.

The supplied `PaymentEntryRow` implementation, if used by that component, contains:

- Payment-mode name and an icon.
- A remove button.
- **Amount** numeric input, `step="0.01"`, `min={0}`.
- Additional fields generated from the selected mode’s `field_config.fields`:
  - Field label and required marker where configured.
  - Bank-account selector for `bank_account_select`, with **Select...** and options displayed as `bank_name - account_number`.
  - Otherwise, a text, number, or date input according to field type.

The shared panel’s submit button uses `config.submitLabel`, is disabled when there are no line items, and shows a loading state while submitting. Its label cannot be stated from the supplied code because the POS preset value is not provided.

## 6.6 Price-list update modal

When party changes with existing lines, the component may evaluate price lists. If the evaluation finds a price change, it opens **Price List Update** (`sm` size).

Exact modal messages and actions:

- Confirmation type:
  - Text: **“A few items have price changes based on the price list. Do you want to apply them?”**
  - Buttons: **No** and **Yes**.
- Force type:
  - Text: **“Prices need to be changed based on the party selection.”**
  - Button: **OK**.

**Yes** or **OK** applies evaluated prices, updates the selected party, and shows **“Prices updated based on party selection”**. For confirmation type, **No** keeps the pending party selection but does not apply evaluated prices. Closing the confirmation-type modal also applies the pending party selection without applying the price rules. The force-type close handler does not perform that confirmation fallback.

## 6.7 Submit workflow and checkout result

The shared form prevents ordinary Enter submission from inputs other than a textarea or button. Submitting the transaction invokes the shared submit handler.

Before invoking the POS checkout callback, it:

1. Requires at least one line; otherwise it returns without submitting.
2. Applies full-payment checks if the POS preset requires full payment.
3. Applies warehouse and currency checks when those options are configured.
4. Validates variant, batch, and serial selections.
5. Builds a transaction payload with type, party, warehouse, transaction date, optional metadata, mapped item lines, payments when enabled, amount tendered when enabled, and subtotal/discount/grand-total values.
6. Sets its submitting state, calls `onSubmit`, and on success clears line items, payments, expenses, and notes and resets the transaction date. It clears warehouse selection only when no default warehouse was supplied.
7. On failure, logs a warning and leaves the relevant submission failure handling to the caller.

The POS checkout handler:

- Rejects submission without a selected terminal with toast **“No POS terminal selected”**, then throws.
- Maps each transaction line to checkout item fields, including UID, item/variant/unit IDs, quantity, unit price, unit discount, free-quantity information, parent UIDs, batch ID, and serial numbers.
- Sets each line’s `tax_rate` to `0`.
- Sets payment method to `multiple` when more than one payment is present; otherwise it uses the first payment mode code, defaulting to `cash`.
- Sends payment amount tendered from the screen or falls back to grand total.
- Maps payment entries into mode details and combines available references, authorization codes, or cheque numbers into a reference string.
- Sends the selected party ID.

On successful checkout:

- The receipt result is stored.
- The print selector opens.
- A **“Checkout complete!”** toast appears.
- The router is refreshed.

On an `INSUFFICIENT_STOCK` system response, the stock-shortage modal opens instead of the generic error toast. Other failures show the response message or **“Checkout failed”** and rethrow an error.

## 6.8 Stock Availability Warning modal

The modal title is **“Stock Availability Warning”**, size `2xl`.

It displays:

- Heading: **“Insufficient Stock”**
- Explanation: **“The transaction cannot be processed because there is not enough stock in the selected warehouse for the following items.”**

The shortage table has columns:

- **Item**
- **Needed**
- **Available**
- **Shortage**

Each item can include its variant name and a **“Batch: …”** line. The quantities are formatted to two decimal places; shortage is calculated as needed quantity minus available quantity.

The modal has a **Close** button.

## 6.9 Receipt print selector

After checkout, `TransactionPrintSelector` receives:

- `transactionType="sales"`
- `entityId={null}`
- `autoPrintTemplateId` from the loaded POS receipt-template setting, if present.

When a receipt exists, the screen maps receipt lines into print items containing:

- Two-digit **index**.
- **description** — item name or `Unknown`, with a non-default variant name when present.
- **qty**
- **unit_price**
- **unit_discount**
- **amount**

It also supplies sale number, payment method, paid/tendered totals, balance due, tax, change due, date, time, cashier/creator, and customer/party values from the receipt and active session data.

When the print selector closes, the screen clears the receipt and increments a reset key, which remounts the product transaction screen for a new sale.

## 6.10 Close session from active POS

Clicking **Close Session** first requests refreshed active-session data, then opens the shared **Close Terminal Session** modal described in the Terminal Sessions section.

On successful close from this screen:

- Local session storage is cleared.
- Active session, selected terminal, and opening balance state are reset.
- The modal closes.
- The page shows **“Session closed successfully!”**.
- The router navigates to `/delivery-notes`.

---

# 7. API and data flow

The supplied code identifies client API functions but does not provide their HTTP method or URL definitions. No API paths are inferred here.

## 7.1 POS sales list and details

The POS Sales page calls:

- `getSalesSettings()` on initial load to read the POS receipt-template setting.
- `getPosSales(params)` for the list. The page sends:
  - `page`
  - `per_page: 15`
  - Optional debounced `search`
  - Optional `date_from`
  - Optional `date_to`
  - Optional `party_id`
- `getPosSale(sale.id)` when a row is opened, to fetch detail data.

The API controller’s list service accepts search, terminal, customer/party, date, payment-method, session, and per-page filters. The UI on this page exposes search, date, and customer filters; it does not expose terminal, payment-method, or session filters.

The list resource includes sale totals, payment fields, status, creation date, and conditionally loaded terminal, session, party, GIN, invoice, cashier, and organization information. The detail service loads GIN lines, item/variant information, units, batches, serial data, invoice payments, and other details used by the modal.

## 7.2 Terminal management

The terminal-management page calls:

- `getTerminals({ page, per_page: 15, search })` for its list.
- `createTerminal(payload)` when adding.
- `updateTerminal(id, payload)` when editing.
- `deleteTerminal(id)` when deleting.

The API list scopes terminals to the resolved organization, supports search and an optional active filter, loads warehouse information, and determines whether a terminal has an open session. Create/update responses drive the form’s success/error toasts.

## 7.3 Terminal sessions

The sessions page calls:

- `getTerminals({ per_page: 1000 })` for filter options.
- `getSessions(params)` for the filtered, paginated list.
- `getSessions({ terminal_id, status: 'open', per_page: 1 })` before opening the close modal, to refresh that terminal’s open-session data.
- `closeSession(sessionId, data)` when submitting the close modal.

The checkout page calls:

- `getActiveSession()` during restoration and again before showing its close modal.
- `getTerminals({ is_active: 1, per_page: 100 })` to populate the session-opening screen.
- `openSession({ terminal_id, opening_balance })` when starting a session.
- `closeSession(sessionId, data)` when closing an active session.

The session API resolves organization context from the `X-Organization-Id` header, request input, or the authenticated user’s first organization. It returns an organization-context error when no organization can be resolved.

## 7.4 Checkout, stock, finance, and receipt flow

Checkout calls `posCheckout(checkoutData)`. The backend code shown then:

- Confirms that the selected terminal exists, belongs to the organization, and is active.
- Uses that terminal’s warehouse for stock availability and outward movement.
- Resolves variants when one is not explicitly provided and the item has a default/first variant.
- Validates available stock and returns shortage data using the `INSUFFICIENT_STOCK` system code when stock is insufficient.
- Calculates line subtotal, discount, tax, grand total, and change.
- Creates a completed goods issue for the POS dispatch and processes outward stock movement.
- Creates an invoice through the finance transaction service when the grand total is greater than zero.
- Associates the POS sale with an open terminal session for the terminal when one is found.
- Creates the POS sale and returns receipt details, including lines, totals, payment data, terminal, cashier, customer, and organization information.

The barcode-resolution controller/service is also supplied: it accepts a barcode, attempts to resolve an organization-owned item or variant, returns item/variant details, sale price and available quantity, and reports **“Barcode not found.”** when no match exists. The supplied POS screen’s visible search uses `transactionLookup`; it does not show a direct call to the barcode-resolution function.

---

# 8. Backend validations and business rules

These rules come from the provided backend request/controller/service code. They are distinct from client-side control behavior.

## 8.1 POS checkout request rules

The checkout request validates:

- `terminal_id`: required integer and must exist as a core terminal.
- `items`: required array with at least one element.
- For every item:
  - `item_id`: required integer and must exist as an inventory item.
  - `variant_id`: nullable integer and, when provided, must exist as an inventory variant.
  - `quantity`: required numeric value, minimum `0.0001`.
  - `unit_price`: required numeric value, minimum `0`.
  - `unit_discount`: nullable numeric value, minimum `0`.
  - `uom_id`: nullable integer and, when provided, must exist as a unit of measure.
  - `tax_rate`: nullable numeric value from `0` through `100`.
  - `batch_id`: nullable integer and, when provided, must exist as an inventory batch.
  - `serial_numbers`: nullable array; each entry must be an integer.
  - `is_free_qty`: nullable boolean.
  - `uid`: nullable string.
  - `parent_line_uids`: nullable array; each entry must be a string.
- `payment`: required array.
- `payment.method`: required and limited to `cash`, `card`, `bank_transfer`, `cheque`, `credit`, `multiple`, or `other`.
- `payment.amount_tendered`: required numeric value, minimum `0`.
- `payment.reference`: nullable string, maximum 255 characters.
- `payment.mode_details`: nullable array.
  - Each `payment_mode_id` is required when mode details are present and must be an integer.
  - Each `amount` is required when mode details are present, numeric, and at least `0`.
  - `mode_metadata` is nullable array.
- `party_id`: nullable integer and, when provided, must exist as a party.
- `remarks`: nullable string.

Custom messages supplied:

- Missing terminal record: **“The selected POS terminal does not exist.”**
- Invalid item ID: **“One or more items are invalid.”**
- Invalid payment method: **“Invalid payment method. Must be cash, card, bank_transfer, cheque, credit, multiple, or other.”**

The checkout controller also requires organization context. It maps a caught HTTP exception with status 404 to a not-found response and other caught HTTP exceptions to an error response.

## 8.2 Session opening rules

The session-opening controller validates:

- `terminal_id`: required integer and must exist.
- `opening_balance`: required numeric value, minimum `0`.

The service then requires the terminal to be active and within the organization. Session behavior includes:

- If the same user already has an open session on a different terminal, it throws **“You already have an open session on another terminal.”**
- If that user already has an open session on the same terminal, the existing session is returned.
- If another user already has an open session on the selected terminal, it throws **“This terminal already has an active session by another user.”**
- Otherwise, an open session is created for the user and terminal.

The UI additionally disables terminals flagged as already in use and locally rejects a missing, nonnumeric, or negative opening balance.

## 8.3 Session closing rules

The close controller validates:

- `actual_closing_balance`: required numeric value, minimum `0`.
- `closing_notes`: nullable string, maximum 1000 characters.
- `handover_to`: nullable integer that must exist as a user.

The service finds an open session in the organization scoped to the authenticated user. If it cannot find one, the controller handles the model-not-found case with **“Session not found or already closed.”**

The expected closing balance is calculated as:

- Opening balance plus cash received during the session.

Cash received is calculated by the supplied service as follows:

- A sale whose payment method is `cash` contributes its grand total.
- A sale whose payment method is `multiple` contributes cash-mode payments for its invoice, less the associated change given.
- Other payment methods do not contribute under this calculation.
- An exception during the calculation results in a returned cash-received value of `0`.

The service records expected balance, actual balance, and the rounded difference, then marks the session closed and sets its closing time. The UI adds its own note requirement when the difference’s absolute value exceeds `0.01`; the supplied backend request validation does **not** make closing notes conditionally required based on the difference.

## 8.4 Checkout calculations and business behavior

The supplied checkout service:

- Uses the active terminal’s warehouse.
- Skips stock requirements for items that do not track stock.
- Applies a unit conversion factor to quantity for stock requirements and outward movement when a unit is supplied and found.
- Calculates each line’s gross subtotal as quantity × unit price.
- Calculates line discount as unit discount × quantity.
- Calculates line tax on the post-discount amount using the supplied tax rate.
- Calculates grand total as subtotal minus discount plus tax, rounded to two decimal places.
- Rejects a tender amount below the grand total with an HTTP 422 error message reporting both amounts.
- Sets change due to the nonnegative difference between amount tendered and grand total.
- Uses the selected party ID or a Walk-In Customer fallback when no party is supplied.
- Treats a `credit` payment method as zero actual amount tendered for the POS sale.
- For multiple payments with mode details, excludes credit-mode entries from the actual tendered amount.
- Creates an invoice only when the grand total is greater than zero.

The UI passes `tax_rate: 0` for each checkout line; this is a UI submission choice, not a backend maximum or a general rule that checkout tax must always be zero.

## 8.5 Shared transaction UI checks

These are client-side checks in `ProductTransactionScreen`, conditional on configuration:

- If full payment is required, total payments must not be below the grand total by more than `0.01`. The message is **“Total payments must equal or exceed the Grand Total (Use Credit mode to pay later).”**
- If overpayment exceeds `0.01`, any positive noncash payment causes **“Overpayment (Change Due) is not supported when using multiple payment methods or non-cash modes.”** For cash-only excess, the shared component adjusts the final cash payment down to the grand total.
- If a warehouse is required first and none is selected, it shows **“Please select a warehouse first.”**
- When currency is enabled and a foreign currency is selected, a missing or nonpositive exchange rate shows **“Exchange Rate is required when a foreign currency is selected.”**
- If a balance remains above `0.01` and no party is selected, it shows **“Customer must be selected for outstanding balances or credit payments.”**
- Where item-level selection is disallowed, an item with variants but no selected variant is rejected with **“Please select a variant for <item name>.”**
- For batch-tracked items, selected batch quantities must match the line quantity when batch selection is required; otherwise it shows **“Please select batches for <item name> to match the total quantity.”**
- For serial-tracked items, selected serial count must exactly match the line quantity when serial selection is required; otherwise it shows **“Please select exactly <quantity> serial numbers for <item name>.”**

## 8.6 Discount behavior: UI versus backend

### UI-only discount behavior

The discount dropdown and input are disabled when **any** of these conditions is true:

1. `config.allowEditPrice` is false.
2. The line is marked as free quantity.
3. The transaction is sales, quotation, or POS and the item is not discountable.
4. The unit price is exactly zero.
5. It is a POS/sales/quotation batch-tracked line with no batch selected.

For an amount discount, the UI clamps the entered per-unit discount to a minimum of zero and a maximum equal to the unit price. For a percentage discount, it clamps the percentage to the range 0–100. These are UI calculations; they are not additional backend validation limits in the supplied checkout request.

The shared UI calculates line discount and line total from the current quantity, unit price, and discount values. A free line is forced to zero unit price, discount, and total.

### Backend discount validation

The supplied checkout backend validates `unit_discount` as nullable numeric with a minimum of `0`. It does **not** specify a maximum discount amount or percentage. The request’s `tax_rate` has its own explicit 0–100 validation, but that limit is not a discount limit.

---

---

## Feature: SETTINGS

# Sales Settings — Detailed UI and Behavior Guide

## 1. Global navigation and entry flow

- **Sidebar label:** Settings
- **Menu group:** Settings
- **Sales menu path:** `/sales/settings`
- **Permission listed in the menu configuration:** `sales_setting.view`
- **Route status:** This page is explicitly listed in the provided Sales menu, so it is **not** a hidden/internal route.
- **Entry flow:** A user with the required permission can open **Sales → Settings** from the Sales menu. The provided code does not show any other page linking to this route.

The page calls `useAuth()` and checks `can('sales_setting.view')`. If that check fails, the settings page content is replaced with an access-denied screen.

## 2. Purpose and scope

The page is titled **Sales Settings** and has the description **“Configure global sales options”**. It provides two settings:

1. Whether sales units can be defined for use in Quotations, Sales Orders, and POS.
2. The default printable template for POS sales receipts.

The page provides a **Save Settings** button that submits the displayed settings. It is therefore **not** a view-only page.

## 3. Page layout and UI elements

### 3.1 Page heading

The authorized page displays a heading area containing:

- A settings icon: `Settings2`, rendered at size 18.
- The heading **Sales Settings**.
- The descriptive text **Configure global sales options**.

### 3.2 Save control

The heading area also contains:

- A **Save Settings** button.
- Clicking it invokes the save handler.
- While a save request is in progress, the button receives `isLoading={true}` through its `isLoading` prop.
- The code does not show the button being disabled during the initial settings load. The settings area can still be showing its loading placeholders while the button is present.

### 3.3 Settings section

The settings area has a header with two labels:

- **Sales Defaults**
- **Status**

The code does not render a separate status value or status badge for either setting. **Status** is the section header’s second label.

While data is loading, the section shows two placeholder rows. Each placeholder row contains placeholder blocks; the code does not show setting names or controls in those rows.

After loading, the section shows two settings rows.

#### Setting row 1: Enable Sales Unit

Visible text:

- **Enable Sales Unit**
- **Allow defining different sales units (e.g. Boxes, Packs) in Quotations, Sales Orders, and POS**

Control:

- A checkbox.
- Its checked state is `settings.enable_sales_unit`.
- Changing it updates that setting in the page’s local state to the checkbox’s checked value.

The code does not show additional controls for defining the units themselves.

#### Setting row 2: POS Receipt Template

Visible text:

- **POS Receipt Template**
- **Select the default printable template for POS sales receipts**

Control:

- A `SearchableSelect`.
- Its placeholder is **Select a template**.
- Its options come from the result of `lookupPrintableTemplates('sales')`.
- The selector is configured to use:
  - `name` as the option label.
  - `id` as the option value.
  - `name` and `template_group.name` as search keys.
- Each rendered option displays the template’s name. If the template has a `template_group.name`, that group name is displayed as well.
- Its initial `defaultValue` is the template option whose `id`, converted to a string, matches `settings.pos_receipt_template_id`.
- When a value is selected, the code stores `String(val)` in `settings.pos_receipt_template_id`.

The code does not specify a separate clear action, an empty option, or any additional template details beyond the name and optional group name.

## 4. Page states and conditional rendering

### 4.1 Permission denied

If `can('sales_setting.view')` returns false, the page returns an access-denied screen instead of the settings interface. It contains:

- A `ShieldAlert` icon.
- The heading **Access Denied**.
- The message **You do not have permission to view or modify sales settings.**

In this state, the component does not call `loadSettings()` because its effect only loads settings when the permission check succeeds. The settings form and **Save Settings** button are not rendered.

### 4.2 Initial state

Before settings have loaded, the component initializes its local state as follows:

- `isLoading`: `true`
- `isSaving`: `false`
- `enable_sales_unit`: `false`
- `pos_receipt_template_id`: an empty string
- `templateOptions`: an empty array

For a permitted user, the component starts loading the settings and printable-template options.

### 4.3 Loading state

While `isLoading` is true:

- The section header remains visible.
- The settings rows are replaced by two loading-placeholder rows.
- The page heading and **Save Settings** button remain part of the rendered authorized page.

The code does not hide or disable the save button based on `isLoading`.

### 4.4 Loaded state

After the loading process finishes successfully, the page renders the two setting rows and their checkbox and searchable selector. The checkbox value and selected template are populated from the loaded settings, subject to the response mapping described below.

### 4.5 Load failure

If either the settings request or the printable-template lookup rejects:

- The page displays the error toast **Failed to load settings**.
- `isLoading` is set to false in the `finally` block.
- Because both requests are awaited together using `Promise.all`, the code only applies the returned settings and template options after both requests have resolved successfully.
- The settings state therefore remains at its existing value if the combined loading operation fails. On the initial load, that means the initial checkbox value and empty template ID remain in state.
- The template options are assigned only when `templatesData?.result` is truthy.

The code does not show a dedicated inline error message or retry control.

### 4.6 Saving state and save result

When the user clicks **Save Settings**:

- `isSaving` becomes true.
- The save request is sent with the current settings.
- On success, the page displays **Settings saved successfully**.
- On failure, the page displays **Failed to save settings**.
- `isSaving` is reset to false in either case, so the button’s loading state ends.

The code does not show a confirmation modal, a separate saved-state indicator, or a navigation change after saving.

## 5. Step-by-step user workflows

### 5.1 Open and inspect Sales Settings

1. Open the listed Sales menu entry **Settings** at `/sales/settings`.
2. The page checks whether the user can access `sales_setting.view`.
3. If permission is denied, read the **Access Denied** message; no settings controls are shown.
4. If permission is granted, the page displays the **Sales Settings** heading and begins loading the settings and printable templates.
5. While loading, the settings section displays two placeholder rows.
6. Once loading finishes, inspect the **Enable Sales Unit** checkbox and **POS Receipt Template** selector.

### 5.2 Change the sales-unit setting

1. Find the **Enable Sales Unit** row.
2. Read its description: **Allow defining different sales units (e.g. Boxes, Packs) in Quotations, Sales Orders, and POS**.
3. Check or uncheck the checkbox.
4. The new checkbox value is stored in the page’s local settings state.
5. Click **Save Settings** to submit the current settings.

The code does not provide a separate save action for this individual checkbox.

### 5.3 Select a POS receipt template

1. Find the **POS Receipt Template** row.
2. Open the selector displaying the placeholder **Select a template**, or the current default value if a matching option is present.
3. Search using the configured template name and template-group name fields.
4. Select an option. The option displays its name and, when present, its group name.
5. Click **Save Settings** to submit the current settings.

The code does not describe how the printable template is rendered on a receipt; it only saves the selected template ID as a sales setting.

### 5.4 Save settings

1. Make any desired changes to the checkbox and/or template selector.
2. Click **Save Settings**.
3. The page sends the current settings to the Sales settings update endpoint.
4. During the request, the button receives its loading state.
5. On success, the page shows **Settings saved successfully**.
6. On failure, the page shows **Failed to save settings**.

The code does not show a discard or reset control. It also does not show a confirmation step before saving.

## 6. API and data flow

### 6.1 Loading Sales settings

The page calls `getSalesSettings()` as part of `loadSettings()`.

- **Method:** `GET`
- **Endpoint:** `${NEXT_PUBLIC_API_URL}/api/sales/settings`
- The client reads the settings from `data.responseData?.result`.
- `enable_sales_unit` is mapped to `true` only when its returned value is exactly the string `'1'`. Other values map to `false`.
- `pos_receipt_template_id` is passed through from the response result.

The page also calls `lookupPrintableTemplates('sales')` during the same load operation. The code provided does not include that helper’s implementation or its endpoint. If the response has a truthy `result`, that result is used as the selector’s options.

### 6.2 Updating Sales settings

When the user saves, `updateSalesSettings(settings)` sends:

- **Method:** `POST`
- **Endpoint:** `${NEXT_PUBLIC_API_URL}/api/sales/settings`
- **Request data shape:**
  - A `settings` object.
  - `enable_sales_unit` is serialized as the string `'1'` when true and `'0'` when false.
  - `pos_receipt_template_id` is included only when it is truthy.

The page does not update its local settings from the save response. It uses the success or failure of the request to show a toast.

### 6.3 Server response behavior

The provided controller’s read action returns a success response with the settings collected as key/value pairs.

The update action:

1. Validates that `settings` is present and is an array.
2. Iterates over the submitted settings.
3. Updates or creates a setting for each submitted key.
4. Returns the resulting settings in its response.

The code does not show the frontend reading or using the returned settings after a save.

## 7. Backend validations and business rules

The backend validation explicitly shown for the update request is:

- `settings` is required.
- `settings` must be an array.

The provided backend code does not show additional validation for individual setting keys or values. It does not specify a backend validation rule for a valid template ID, a particular set of allowed keys, or a numeric or percentage limit.

The following behaviors are visible in the frontend and should be distinguished from backend validation:

- The checkbox is represented in the request as `'1'` or `'0'`.
- The client includes the template ID only when `pos_receipt_template_id` is truthy.
- The client treats the loaded `enable_sales_unit` value as enabled only when it equals the string `'1'`.
- The page gates access to the settings interface using `can('sales_setting.view')`.

These frontend behaviors do not establish additional backend validation rules.

## 8. Modals, record creation, and other controls

- **Modals:** None are shown in the provided code.
- **Record-creation form:** None is shown.
- **Create button:** None is shown.
- **Save control:** The page does include an explicit **Save Settings** button for updating these settings.
- **Other settings controls:** The code shows only the checkbox and searchable template selector described above.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---

## Feature: PRICE-LISTS

# Price Lists — Detailed UI and Workflow Guide

## 1. Global navigation and entry flow

The supplied global menu defines this Sales sidebar entry:

- **Sales → Master Data → Price Lists**
- Label: **Price Lists**
- Path: `/sales/price-lists`

The list page also links to a detail page using `router.push(`/price-lists/${list.id}`)`. That route is **not listed in the supplied global menu**. It is therefore a hidden/internal route under the navigation rules provided. A user can reach it from the Price Lists list by clicking a row or choosing **View** in that row’s actions menu.

The detail page’s back button navigates to `/price-lists`, exactly as written in the code. The code does not send that button to `/sales/price-lists`.

No other sidebar paths are asserted here.

## 2. Overview

The feature lets users manage price lists and their pricing rules:

- The list page displays price lists and provides controls to search, create, edit, view, and delete them.
- Each price list’s detail page displays its rules and provides controls to add, edit, and delete rules.
- A price list can be targeted to all parties, a specific customer group, or a specific customer; it can also be scoped to a location and have start and end dates.
- A rule can apply to all products, selected categories, selected brands, or selected items. Rule forms include minimum-quantity and pricing inputs.

The code contains explicit creation and save controls on both the price-list list page and the detail page. **The view-only warning does not apply to these pages.**

There is no `<ProductTransactionScreen>` in the supplied code, so no fields from that component are applicable.

## 3. Price Lists page — `/sales/price-lists`

### Page header and controls

The page heading is **Price Lists**. Beneath it, the supporting text reads:

> Manage pricing for specific customers or groups.

A **RecordCount** component is rendered in two header locations when `isLoading` is false: one beside the heading and another in the right-side controls. Both use the calculated `total` value.

The right-side controls contain:

1. **DesktopSearchPopover**
   - Receives the current `search` value.
   - Updates the page’s search state through `onSearchChange`.
   - The source does not show the popover’s internal fields or text, so none are specified here.
2. **Add Price List**
   - Primary button with a plus icon.
   - Clears the selected list by setting it to `null`, then opens the price-list modal in create mode.

### Pricing priority banner

The page displays **PricingPriorityBanner** above the list content unless the user has previously dismissed it.

Initially, the banner says:

> **Pricing Note:** For an item, only one price list will apply at a time based on targeting priority.

It includes a details toggle:

- Initially: **View Priority Logic**, with a down-chevron.
- When expanded: **Hide Details**, with an up-chevron.

Expanded priority order, from highest to lowest:

1. Specific Location + Specific Customer (Highest Priority)
2. Specific Location + Customer Group
3. Specific Location + All Customers
4. All Locations + Specific Customer
5. All Locations + Customer Group
6. All Locations + All Customers (Lowest Priority)

The expanded banner also says:

> If you want to manage multi-quantity pricing rules, please add them within the **same** price list.

The **Understood** button dismisses the banner and writes `true` to local storage under `local_storage.hide_pricing_note`. On a later mount, the banner checks that value; if it is `true` or `"true"`, the banner is hidden. The banner component does not show a separate confirmation dialog.

### List content states

#### Initial loading with no rows yet

If `isLoading` is true and the current `priceLists` array is empty, the page renders a table header and a loader.

The eight columns are:

1. **Name**
2. **Code**
3. **Status**
4. **Valid From**
5. **Valid To**
6. **Location**
7. **Target**
8. **Actions**

The table body contains a loader configured for eight columns.

#### Empty results

If the list is not in the initial-loading branch and `priceLists` is empty, the page displays:

- Title: **No Price Lists Found**
- Description: **Get started by creating a new price list.**
- Button: **Create Price List**

Clicking **Create Price List** clears the selected list and opens the same modal used by **Add Price List**, in create mode.

#### Results table

When price lists are present, the table has the same eight columns as the loading table. Each row displays:

- **Name:** `list.name`
- **Code:** `list.code`
- **Status:**
  - **Active** if `list.is_active` is truthy.
  - **Inactive** otherwise.
- **Valid From:**
  - Formatted with `format(new Date(list.start_date), "PP")` when a start date exists.
  - A hyphen (`-`) when it does not.
- **Valid To:**
  - Formatted with `format(new Date(list.end_date), "PP")` when an end date exists.
  - A hyphen (`-`) when it does not.
- **Location:**
  - `list.organization.name` when an organization exists.
  - **All Locations** otherwise.
- **Target:**
  - `Customer: {first_name} {last_name}` when `list.party` exists.
  - `Group: {party_group.name}` when there is no party and a party group exists.
  - **Global** when neither exists.
- **Actions:** a three-dot menu.

Clicking the row itself navigates to `/price-lists/{id}`.

#### Row actions menu

The three-dot menu is aligned to the right and contains:

- **View**
  - Navigates to `/price-lists/{id}`.
  - Closes the dropdown.
- **Edit**
  - Selects the current list.
  - Opens the price-list modal in edit mode.
  - Closes the dropdown.
- **Delete**
  - Opens a confirmation control with:
    - Title: **Delete Price List?**
    - Body: **Are you sure you want to delete this price list? This action cannot be undone.**
  - On confirmation, the UI sets the confirmation control’s loading state, calls the delete operation, clears the loading state, closes the confirmation control, and closes the dropdown.
  - On success, a toast says **Price list deleted successfully** and the list data is refreshed.
  - On failure, a toast displays `error.message` or, if unavailable, **Failed to delete price list**.

The row’s menu container stops click propagation, so using the menu does not trigger the row navigation.

### Price-list modal — create and edit

The list page renders `PriceListFormModal`. Its title depends on whether `initialData` is present:

- Create mode: **Create Price List**
- Edit mode: **Edit Price List**

The modal size is `lg`. Its fields and controls are as follows.

#### Fields

1. **Name**
   - Text input.
   - Required indicator is shown.
   - Placeholder: `e.g. VIP Pricing`
   - Displays `errors.name` when present.

2. **Code**
   - Text input.
   - Required indicator is shown.
   - Placeholder: `e.g. VIP`
   - Displays `errors.code` when present.

3. **Applicable To**
   - Select control.
   - Options and visible labels:
     - Value `All`: **All Parties**
     - Value `Specific Customer Group`: **Specific Party Group**
     - Value `Specific Customer`: **Specific Party**
   - The form’s internal default is `All`.

4. **Party Group** — shown only when Applicable To is **Specific Customer Group**
   - Async searchable select.
   - Placeholder: `Search group...`
   - Loads party groups using `getPartyGroups({ per_page: 20, page, search })`.
   - Uses `name` as the displayed label and `id` as the value.
   - A selected value is converted to a number and stored as `party_group_id`; clearing it stores `null`.

5. **Party** — shown only when Applicable To is **Specific Customer**
   - Async searchable select.
   - Placeholder: `Search party...`
   - Loads customer parties using `getPartiesLookup({ limit: 50, search, role: 'customer' })`.
   - Requests after page 1 return an empty list.
   - The option label uses `p.name`, then `p.full_name`, then **Unknown**.
   - Uses `id` as the value.
   - A selected value is converted to a number and stored as `party_id`; clearing it stores `null`.

6. **Applicable Location**
   - Async searchable select.
   - Placeholder: **All Locations**
   - Clear is allowed.
   - Loads organizations using `getOrganizationsLookup({ limit: 50, search })`.
   - Requests after page 1 return an empty list.
   - Uses `name` as the displayed label and `id` as the value.
   - A selected value is converted to a number and stored as `organization_id`; clearing it stores `null`.

7. **Start Date**
   - Date input.
   - Displays `errors.start_date` when present.

8. **End Date**
   - Date input.
   - Displays `errors.end_date` when present.

9. **Description**
   - Textarea.
   - Placeholder: `Optional description`
   - Displays `errors.description` when present.

10. **Active**
    - Checkbox.
    - Checked state is backed by `formData.is_active`.

#### Applicable-to behavior

Changing **Applicable To** clears or resets target identifiers as follows:

- **All** clears both `party_id` and `party_group_id`.
- **Specific Customer Group** clears `party_id`.
- **Specific Customer** clears `party_group_id`.

When editing, the initial selection is derived from `initialData`:

- `party_id` present → **Specific Customer**
- Otherwise, `party_group_id` present → **Specific Customer Group**
- Otherwise → **All**

When opening the modal for a new list, the form is reset to empty text fields, null party/group/location identifiers, empty dates, and `is_active: true`.

#### Modal footer and submission

The footer contains:

- **Cancel**
  - Closes the modal.
  - Disabled while the modal is loading.
- Primary submit button:
  - **Create Price List** in create mode.
  - **Save Changes** in edit mode.
  - Displays its loading state while submission is in progress.

Clicking submit applies these client-side checks in order:

1. If `name` is empty, the modal sets `errors.name` to **Name is required** and stops.
2. If `code` is empty, the modal sets `errors.code` to **Code is required** and stops.
3. Otherwise, it submits the form data. Empty `start_date` and `end_date` values are sent as `null`.

Create mode calls `createPriceList(payload)` and shows **Price list created successfully** on success.

Edit mode calls `updatePriceList(initialData.id, payload)` and shows **Price list updated successfully** on success.

After success, the modal invokes `onSuccess` (which refreshes the list) and closes. If the server response contains `error.response.data.errors`, the first message for each returned key is placed in the modal’s field-error map. Other failures produce a toast using `error.message` or **An error occurred**.

## 4. Price-list detail page — `/price-lists/[id]`

This route is linked from the list page but is not separately present in the provided global menu, so it is a hidden/internal route under the stated navigation rules.

The page obtains the route ID from `params`, parses it as an integer, and loads the price list and its rules.

### Detail-page loading and missing-record states

- While the price list request is loading and no price list has been received, the page shows **Loading price list...**
- If loading has finished or the data is otherwise absent and `priceList` is falsy, the page shows **Price List not found.**

The rule-loading state is handled separately within the rules area.

### Detail header

For a found price list, the header contains:

- A back-arrow button.
  - Clicking it navigates to `/price-lists`.
- The price-list name as the heading.
- A supporting line in the format:
  - `{priceList.code} • {rules.length} rules`
- **Add Rule**
  - Primary button with a plus icon.
  - Clears the selected rule and opens the rule modal in create mode.

### Rule priority banner

The detail page displays **RulePriorityBanner** above the rules table.

Initially it says:

> **Rule Note:** Within a price list, only one rule will apply to an item based on targeting priority.

Its toggle is initially **View Priority Logic** and changes to **Hide Details** when expanded.

Expanded priority order:

1. Specific Item / Variant (Highest Priority)
2. Specific Category or Brand
3. All Items (Lowest Priority)

The expanded banner also states:

> If multiple rules match at the same priority level, the rule with the **highest** matched minimum quantity is applied.

The **Understood** button hides the banner and stores `true` under `local_storage.hide_rule_note`. On a later mount, the banner checks for `true` or `"true"` and remains hidden if found.

### Rule list states

#### Loading rules with no rules yet

When rules are loading and the `rules` array is empty, the page displays a table header and a five-column loader.

The columns are:

1. **Target**
2. **Min. Qty**
3. **Rate**
4. **Markdown**
5. **Actions**

#### No rules

When the rules array is empty outside the loading branch, the page displays:

- Title: **No Price Rules Found**
- Description: **Get started by creating a new price rule for this list.**
- Button: **Create Price Rule**

Clicking the button clears the selected rule and opens the rule modal in create mode.

#### Rules table

When rules exist, each row displays:

- **Target**
  - Item rule: `Item: {item.name}`.
  - If the item has variants and the rule has a variant name, the variant name is appended as ` - {variant_name}`.
  - If there is a batch, `(Batch: {batch_number})` is appended.
  - Category rules display `Category: ` followed by category names joined with commas.
  - Brand rules display `Brand: ` followed by brand names joined with commas.
  - When there is no item, category, or brand target, the target is **All Items**.
- **Min. Qty**
  - Shows `Number(rule.min_quantity).toFixed(2)` when `rule.min_quantity` is truthy.
  - Otherwise shows `-`.
- **Rate**
  - Shows `Number(rule.rate).toFixed(2)` when `rule.rate` is truthy.
  - Otherwise shows `-`.
- **Markdown**
  - Shows `{rule.markdown_percentage}%` when `rule.markdown_percentage` is truthy.
  - Otherwise shows `-`.
- **Actions**
  - Three-dot dropdown with **Edit** and **Delete**.

#### Rule row actions

- **Edit**
  - Selects the rule and opens the modal in edit mode.
  - Closes the dropdown.
- **Delete**
  - Opens a confirmation control with:
    - Title: **Delete Price Rule?**
    - Body: **Are you sure you want to delete this price rule? This action cannot be undone.**
  - On confirmation, the UI sets the confirmation loading state, calls the delete operation, clears loading, and closes the confirmation and dropdown.
  - On success, a toast says **Price rule deleted successfully**. Both the list and rule data are refreshed.
  - On failure, a toast displays `error.message` or **Failed to delete price rule**.

## 5. Price-rule modal — create and edit

The detail page renders `PriceRuleFormModal`. It receives the current price-list ID and, when editing, the selected rule.

Modal title:

- Create mode: **Create Price Rule**
- Edit mode: **Edit Price Rule**

The modal size is `md`.

### Applicable Product selector

The first control is **Applicable Product**, with these options:

- **All Products**
- **Specific Categories**
- **Specific Brands**
- **Specific Items**

The default is **All Products**. Changing the selection clears `item_ids`, `category_ids`, and `brand_ids` from the general form data.

When the modal opens, it loads categories with `getCategoriesLookup({ per_page: 100 })` and brands with `getBrandsLookup({ per_page: 100 })`.

### Target controls by product selection

#### Specific Categories

Displays a multiple-selection **Categories** control:

- Placeholder: `Search categories...`
- Options come from the loaded categories.
- Uses category `name` as the label and `id` as the value.
- Selected values are converted to numeric IDs and stored in `category_ids`.

#### Specific Brands

Displays a multiple-selection **Brands** control:

- Placeholder: `Search brands...`
- Options come from the loaded brands.
- Uses brand `name` as the label and `id` as the value.
- Selected values are converted to numeric IDs and stored in `brand_ids`.

#### Specific Items

Displays a multiple-selection async **Items** control:

- Placeholder: `Search items...`
- Loads items using `getItemsLookup({ limit: 50, search, is_available_sell: 1 })`.
- Requests after page 1 return an empty list.
- For an item with variants, each variant is offered as a separate option named `{item.name} - {variant_name}`.
- For an item without variants, the option is the item name.
- The option data includes item ID, variant ID where relevant, and tracking type.

When selected options are processed:

- Existing item rules are retained when their generated option ID matches.
- A new rule row is initialized with:
  - Minimum quantity `1`
  - Empty fixed price
  - Empty markdown
- For an option whose tracking type is `batch`, the modal loads batches using `getItemBatches(item_id, { variant_id })` when a variant ID exists, or `getItemBatches(item_id, {})` otherwise.
- For each returned batch, the modal adds a batch rule row named `Batch: {batch_number}`, unless that row already exists.
- Batch rows are visually indented and marked with a corner-down-right icon.

When item rules exist, the modal displays a table with these exact headings:

1. **Item**
2. **Min Qty**
3. **Fixed Price**
4. **Markdown %**

Each row has these inputs:

- **Min Qty**
  - Number input with `min="1"`.
  - Initialized to `1`.
- **Fixed Price**
  - Number input with `step="0.01"`.
- **Markdown %**
  - Number input with `step="0.01"` and `max="100"`.

For a row, entering a non-empty fixed price clears that row’s markdown value. Entering a non-empty markdown clears that row’s fixed price.

The provided markup does not include a separate remove button for an individual rule row.

### General quantity and markdown controls

For all selections other than **Specific Items**, the modal shows:

1. **Min. Quantity**
   - Number input.
   - `min="1"`.
   - Initialized to `1`.
   - Marked `required`.
   - Displays `errors.min_quantity` if present.

2. **Markdown %**
   - Number input.
   - `step="0.01"`, `min="0"`, and `max="100"`.
   - Placeholder: `%`
   - Displays `errors.markdown_percentage` if present.

These HTML input attributes describe UI behavior; they are not, by themselves, evidence of backend validation limits.

### Rule submission behavior

Before submission, the modal checks targets for non-All-Products modes:

- **Specific Items** requires at least one `specificItemsRules` entry.
- **Specific Categories** requires at least one category ID.
- **Specific Brands** requires at least one brand ID.

If the applicable target is empty, it shows the inline target error:

> Please select at least one item, category, or brand

For **Specific Items**:

- Each selected item or batch row must have either a fixed price or a markdown value.
- If any row has neither, the modal shows the toast:
  > Please provide either a fixed price or markdown for all selected items.
- The submitted rules include:
  - `item_id`
  - `variant_id`
  - `batch_id` or `null`
  - `min_quantity`, parsed as a number with fallback to `1`
  - `rate`, parsed as a number or sent as `null`
  - `markdown_percentage`, parsed as a number or sent as `null`
- In create mode, the modal calls `batchCreatePriceRules(priceListId, { rules })` and shows **Price rules created successfully**.
- In edit mode, if the generated payload contains at least one rule, it calls `updatePriceRule` for `initialData.id` using the first rule and shows **Price rule updated successfully**.

For **All Products**, **Specific Categories**, and **Specific Brands**:

- A markdown percentage is required by the modal’s submission logic. If it is empty, the modal sets `errors.markdown_percentage` to **Provide a markdown percentage** and stops.
- The payload sets `rate` to `null`.
- `item_ids` is sent as an empty array.
- `category_ids` is sent only for **Specific Categories**; otherwise it is empty.
- `brand_ids` is sent only for **Specific Brands**; otherwise it is empty.
- `min_quantity` is parsed as a number with fallback to `1`.
- `markdown_percentage` is parsed as a number.
- In create mode, the modal calls `createPriceRule` and shows **Price rule created successfully**.
- In edit mode, it calls `updatePriceRule` and shows **Price rule updated successfully**.

After successful submission, `onSuccess` refreshes both the price-list data and rule data, and the modal closes.

The footer contains:

- **Cancel**, disabled while loading.
- **Create Rule** in create mode, or **Save Changes** in edit mode; this button displays a loading state during submission.

If the API response contains field errors at `error.response.data.errors`, the modal uses the first returned message for each key as a field error. Other failures show a toast using `error.message` or **An error occurred**.

## 6. Step-by-step workflows

### Create a price list

1. Open **Sales → Master Data → Price Lists** using the menu path `/sales/price-lists`.
2. Click **Add Price List** in the header, or **Create Price List** in the empty state.
3. Enter a **Name** and **Code**.
4. Choose **Applicable To**:
   - Keep **All Parties**, or choose **Specific Party Group** and select a group, or choose **Specific Party** and select a party.
5. Optionally select an **Applicable Location**.
6. Optionally set **Start Date**, **End Date**, and **Description**.
7. Leave **Active** checked or uncheck it.
8. Click **Create Price List**.
9. If the modal’s required name or code check fails, correct the indicated field. If submission succeeds, the modal closes and the list refreshes.

### Edit a price list

1. In a populated list, open the row’s three-dot menu.
2. Choose **Edit**.
3. Update the fields in **Edit Price List**.
4. Click **Save Changes**.
5. On success, the modal closes and the list refreshes.

### View a price list and its rules

1. Click a price-list row or open its three-dot menu and choose **View**.
2. The UI navigates to `/price-lists/{id}`.
3. The detail page shows the list name, code, and number of rules.
4. Review the rules table, or expand **View Priority Logic** to see rule targeting priority.
5. Use the back-arrow button to navigate to `/price-lists`.

### Add a price rule

1. On a price-list detail page, click **Add Rule**, or click **Create Price Rule** when the rules list is empty.
2. Select an **Applicable Product** scope.
3. Select categories, brands, or items when the chosen scope requires them.
4. For **Specific Items**, enter a minimum quantity and either a fixed price or markdown for each displayed item or batch row.
5. For other scopes, enter a minimum quantity and a markdown percentage.
6. Click **Create Rule**.
7. Correct any inline target or markdown error, or address any toast message.
8. After success, the modal closes and the detail data refreshes.

### Edit a price rule

1. Open the rule row’s three-dot menu and choose **Edit**.
2. Change the applicable product scope or the displayed target and pricing values.
3. Click **Save Changes**.
4. On success, the modal closes and both the list and rules data are refreshed.

### Delete a price list

1. Open the list row’s three-dot menu.
2. Choose **Delete**.
3. Review the confirmation:
   - **Delete Price List?**
   - **Are you sure you want to delete this price list? This action cannot be undone.**
4. Confirm the action in the confirmation control.
5. On success, the page shows **Price list deleted successfully** and reloads the list data.

### Delete a price rule

1. Open the rule row’s three-dot menu.
2. Choose **Delete**.
3. Review the confirmation:
   - **Delete Price Rule?**
   - **Are you sure you want to delete this price rule? This action cannot be undone.**
4. Confirm the action in the confirmation control.
5. On success, the page shows **Price rule deleted successfully** and refreshes the price list and rules.

## 7. API and data flow

The client API helper builds its base URL from `NEXT_PUBLIC_API_URL`. It provides GET, POST, PUT, and DELETE wrappers through `sendRequest`. If a request is not successful, the helper throws an object containing the response data under `response.data`.

### Price-list requests

- List and search:
  - `GET /api/sales/price-lists`
  - The list page passes `{ search }` as query parameters.
- Fetch one list:
  - `GET /api/sales/price-lists/{id}`
- Create:
  - `POST /api/sales/price-lists`
- Update:
  - `PUT /api/sales/price-lists/{id}`
- Delete:
  - `DELETE /api/sales/price-lists/{id}`

The list page uses SWR with the key `["price-lists", search]`. After a successful create, edit, or delete, it refreshes the list data through `mutate()`.

### Price-rule requests

- Fetch rules:
  - `GET /api/sales/price-lists/{listId}/rules`
- Create one general rule:
  - `POST /api/sales/price-lists/{listId}/rules`
- Create item rules in a batch:
  - `POST /api/sales/price-lists/{listId}/rules/batch`
- Update a rule:
  - `PUT /api/sales/price-lists/{listId}/rules/{ruleId}`
- Delete a rule:
  - `DELETE /api/sales/price-lists/{listId}/rules/{ruleId}`

The detail page uses separate SWR requests for the list and rules. Successful rule creation or editing refreshes both through the modal’s `onSuccess` callback. Successful deletion also refreshes both.

### Lookup requests invoked by the forms

The supplied code shows these lookup-function calls, but does not provide their endpoint definitions:

- Customer parties: `getPartiesLookup`
- Party groups: `getPartyGroups`
- Organizations: `getOrganizationsLookup`
- Categories: `getCategoriesLookup`
- Brands: `getBrandsLookup`
- Sellable items: `getItemsLookup`
- Item batches: `getItemBatches`

No lookup URLs are inferred here.

## 8. Validation and business rules evidenced by the supplied code

### Client-side checks and UI behavior

- Price-list **Name** is checked for an empty value and produces **Name is required**.
- Price-list **Code** is checked for an empty value and produces **Code is required**.
- The price-list form sends blank start and end dates as `null`.
- Applicable-to changes clear conflicting party or party-group identifiers as described above.
- A non-All-Products price rule must have at least one target in its selected target category.
- General, non-Specific-Items rule submission requires a markdown percentage; an empty value produces **Provide a markdown percentage**.
- Each Specific Items row must have a fixed price or markdown; otherwise the modal displays the corresponding toast.
- Specific Items fixed price and markdown inputs clear one another when a non-empty value is entered in either field.
- The quantity inputs have `min="1"` attributes.
- The general markdown input has `min="0"` and `max="100"` attributes; the Specific Items markdown input has `max="100"`. These are visible input attributes, not proof of backend validation.
- Numeric values are parsed with `parseFloat` when creating rule payloads. For general rules, minimum quantity falls back to `1` if its value is empty.
- Some errors returned by the API are displayed by mapping the first error message for each field key into the modal’s error state.

### Backend validation availability

No `--- EXTRACTED BACKEND VALIDATIONS ---` content or backend validation source was included in the supplied material. Therefore, no backend-specific validation limits or business rules can be confirmed here. The checks listed above are only those explicitly implemented or represented in the supplied frontend code.

**Note:** Features related to Inventory, Jewelry, Core, and Finance (including specific physical items like watches or gold) are managed in their respective modules.

---



---
### Generation Metrics
- **Input Tokens**: 182,867 ($0.02743)
- **Output Tokens**: 66,359 ($0.03982)
- **Total Cost**: $0.06725
- **Overall AI Confidence Score**: 98.50%



---

<a name="module-inventory"></a>
## Module: INVENTORY


The Inventory module provides complete control over item catalogs, real-time multi-warehouse stock balances, 
tracking hierarchies (serial and batch numbers), stock movements (stock ledger), adjustments, inter-warehouse 
transfers, cycle counts, and valuation methods (FIFO, Weighted Average, and Specific Identification).

### Feature: INVENTORY ITEMS CATALOG

#### 1. Global navigation and entry flow
- **Route:** `/inventory/items`
- **Menu label:** Items
- **Menu key:** `inventory__items`
- **Default Group:** Catalog
- **Required Permission:** `inventory_item.view`
- **Access Flow:** Sidebar ➔ Inventory ➔ Catalog ➔ Items.

#### 2. Overview
The Items page is the central master repository for all physical, non-physical, variant, and serialized products. 
Users can browse all catalog items, search by SKU, item name, or barcode, filter by category or status, view detailed 
specifications, and create or update items.

#### 3. Page layout and visible elements
- **Heading:** `Items`
- **Header Actions:**
  - `+ Add Item` primary button (opens full item creation modal).
  - `Export CSV / Excel` secondary action dropdown.
- **Search & Filters:**
  - `DesktopSearchPopover` (Placeholder: `Search by item name, SKU, or barcode...`).
  - Category Filter Dropdown (All Categories or specific category).
  - Status Filter Pills: `All`, `Active`, `Draft`, `Archived`.
- **Table Columns:**
  1. **SKU:** Unique item product code.
  2. **Item Name:** Product name with thumbnail image preview.
  3. **Category:** Assigned category with badge color.
  4. **Base UOM:** Primary unit of measure (e.g., PCS, KG, LTR, BOX).
  5. **Stocking UOM:** Secondary unit used for storage.
  6. **Tracking Type:** Badge displaying `None`, `Batch/Lot`, or `Serial Number`.
  7. **Status:** `Active` (green pill) or `Inactive` (gray pill).
  8. **Actions:** Three-dot dropdown menu triggered by `<MoreVertical size={20} />`:
     - `View Details`: Opens comprehensive `ItemDetailModal`.
     - `Edit`: Opens edit drawer.
     - `Adjust Stock`: Quick redirect to Stock Adjustments for this item.
     - `Delete`: Soft deletes item with PopConfirm modal.

#### 4. Detail Modals & Forms
- **Item Creation Modal (`ItemFormModal`):**
  - **Identity Tab:**
    - `Item Name *` (Required string, max 255 chars).
    - `SKU *` (Required string, max 100 chars, unique across active catalog).
    - `Barcode` (Optional, alphanumeric string).
    - `Description` (Optional multi-line text).
  - **Classification Tab:**
    - `Category *` (Required select dropdown linked to `inventory_categories`).
    - `Brand` (Optional select dropdown linked to `inventory_brands`).
    - `Base UOM *` (Required select dropdown linked to `inventory_uom`).
  - **Inventory Tracking & Costing:**
    - `Tracking Type`: Radio selection between `None` (standard quantity), `Batch` (batch number + expiry date required), or `Serial` (unique serial per unit).
    - `Valuation Method`: `FIFO` (First-In First-Out), `Weighted Average`, or `Specific Identification` (automatically forced if Tracking Type is `Serial`).
    - `Tracks Stock` (Toggle, default TRUE).
    - `Negative Stock Allowed` (Toggle, default FALSE).
  - **Sales & Commercial Attributes:**
    - `Is Available for Sale` (Toggle, default TRUE).
    - `Is Discountable` (Toggle, default TRUE. When set to FALSE, the discount input on POS and Sales Order lines is disabled/greyed out).
    - `Is Taxable` (Toggle, default TRUE).
    - `Is Returnable` (Toggle, default TRUE).
    - `Standard Selling Price` (Numeric currency input).

#### 5. Step-by-Step Workflows
- **How to Create a New Catalog Item:**
  1. Go to **Sidebar ➔ Inventory ➔ Catalog ➔ Items**.
  2. Click **'+ Add Item'** at the top right.
  3. Fill in the required fields: `Item Name`, `SKU`, `Category`, and `Base UOM`.
  4. Select the `Tracking Type` (`None`, `Batch`, or `Serial`).
  5. Configure commercial flags: ensure `Is Available for Sale` and `Is Discountable` are enabled if applicable.
  6. Click **'Save Item'**. The new item immediately appears in the items table.
- **How to View Live Stock and Batches of an Item:**
  1. In the items table, click on the item row to open `ItemDetailModal`.
  2. Switch between tabs:
     - **Overview:** General specifications and commercial flags.
     - **Warehouses:** Live breakdown of quantities on-hand, allocated, and available per warehouse.
     - **Batches / Lots:** Displays batch numbers, manufacturing dates, expiry dates, and remaining stock.
     - **Serials:** Lists all individual registered serial numbers and their current warehouse status.

#### 6. API & Data Flow
- `GET /api/inventory/items`: Paginated item list with filters `search`, `category_id`, `status`.
- `POST /api/inventory/items`: Creates new item.
- `GET /api/inventory/items/{id}`: Detailed item profile including stock balances and variants.
- `PUT /api/inventory/items/{id}`: Updates item attributes.
- `DELETE /api/inventory/items/{id}`: Soft deletes item (requires permission `inventory_item.delete`).

#### 7. Backend Validations & Business Rules
- **SKU Uniqueness:** The SKU must be unique across the tenant's catalog (`unique:inventory_items,sku`) unless the organization setting `item_sku_can_duplicate` is explicitly set to `true`.
- **Serial Valuation Lock:** When `tracking_type` is set to `serial`, the backend automatically overrides and enforces `valuation_method = 'specific'`. Serialized items cannot use weighted average.
- **Non-Deletable with Stock:** An item cannot be deleted if it has remaining positive stock balance (`qty_available > 0`) in any warehouse.

---

### Feature: INVENTORY ITEM CATEGORIES

- **Route:** `/inventory/categories`
- **Menu label:** Categories
- **Default Group:** Catalog
- **Access Flow:** Sidebar ➔ Inventory ➔ Catalog ➔ Categories.

Categories are managed on the Categories screen. The Category dropdown on an item form selects an existing category; it does not document category creation on Items.

To add an inventory category:
1. Open **Sidebar ➔ Inventory ➔ Catalog ➔ Categories**.
2. Click **Add Category**. This opens the **Add New Category** modal.
3. Enter **Name** (required). **Code** and **Description** are optional.
4. To create a subcategory, select **Parent Category**. Leave it at **None (Root Level)** for a root category.
5. Choose **Status**: **Active** or **Inactive**; a new category defaults to Active.
6. Click **Create Category**. On success the modal closes and the category list refreshes.

To change a category, use **Edit Category**, update its fields, and click **Update Category**.

Verified implementation sources: `packages/core-lib/src/constants/menus.ts` (inventory__categories) and `apps/common-ui/inventory-ui/app/categories/_route/components/CategoryList.tsx` (openCreate, renderForm, handleSubmit, Add Category and Add New Category).

---

### Feature: STOCK OVERVIEW & WAREHOUSE BALANCES

#### 1. Global navigation and entry flow
- **Route:** `/inventory/stock`
- **Menu label:** Stock Overview
- **Menu key:** `inventory__stock`
- **Default Group:** Stock
- **Required Permission:** `inventory_stock.view`
- **Access Flow:** Sidebar ➔ Inventory ➔ Stock ➔ Stock Overview.

#### 2. Overview
Provides an aggregated real-time view of inventory across all physical and virtual warehouses. Shows 
Quantity On Hand, Quantity Allocated (reserved for approved sales orders/transfers), and Quantity Available for Sale.

#### 3. Page layout and visible elements
- **Heading:** `Stock Overview`
- **Filters:**
  - Warehouse Selector: Dropdown of active warehouses (or "All Warehouses").
  - Stock Level Filter: `All`, `In Stock`, `Low Stock` (below reorder point), `Out of Stock` (`qty_available == 0`).
- **Table Columns:**
  1. **Item Name & SKU:** Product title, SKU, and category badge.
  2. **Warehouse:** Name of storage facility.
  3. **On Hand Qty:** Physical quantity physically inside the warehouse.
  4. **Allocated Qty:** Quantity committed to open orders or pending delivery.
  5. **Available Qty:** Net quantity (`On Hand - Allocated`) ready for checkout.
  6. **Reorder Point:** Minimum inventory threshold before trigger alert.
  7. **Status Pill:** Green (`In Stock`), Orange (`Low Stock`), Red (`Out of Stock`).

#### 4. Step-by-Step Workflows
- **How to Check Available Stock for a Sale:**
  1. Open **Sidebar ➔ Inventory ➔ Stock ➔ Stock Overview**.
  2. Enter the item name or SKU into the search box.
  3. Inspect the **Available Qty** column under your target warehouse. If Available Qty is `0`, POS and Sales checkout will block sales addition.

---

### Feature: STOCK MOVEMENTS & AUDIT LEDGER

#### 1. Global navigation and entry flow
- **Route:** `/inventory/ledger`
- **Menu label:** Stock Movements
- **Menu key:** `inventory__ledger`
- **Default Group:** Stock
- **Required Permission:** `inventory_ledger.view`
- **Access Flow:** Sidebar ➔ Inventory ➔ Stock ➔ Stock Movements.

#### 2. Overview
An immutable audit log recording every single inventory transaction: Goods Receipts (GRN), Sales Goods Issue Notes (GIN), 
Returns, Inter-Warehouse Transfers, and Stock Adjustments.

#### 3. Table Columns
1. **Date & Time:** Timestamp of transaction posting.
2. **Transaction Type:** `PURCHASE_RECEIPT`, `SALES_DELIVERY`, `TRANSFER_IN`, `TRANSFER_OUT`, `ADJUSTMENT_ADD`, `ADJUSTMENT_DEDUCT`.
3. **Reference Document:** Hyperlink to source document (e.g., `PO-2026-0042`, `GIN-8891`, `ADJ-0012`).
4. **Item & SKU:** Item moved.
5. **Warehouse:** Warehouse affected.
6. **Qty Changed:** Signed number (`+50` or `-12`).
7. **Unit Cost:** Cost at time of transaction.
8. **Running Balance:** Resulting warehouse balance after posting.
9. **User:** Staff member who authorized the transaction.

---

### Feature: STOCK ADJUSTMENTS & WRITE-OFFS

#### 1. Global navigation and entry flow
- **Route:** `/inventory/adjustments`
- **Menu label:** Adjustments
- **Menu key:** `inventory__adjustments`
- **Default Group:** Operations
- **Required Permission:** `inventory_adjustment.view`
- **Access Flow:** Sidebar ➔ Inventory ➔ Operations ➔ Adjustments.

#### 2. Overview
Allows authorized supervisors to reconcile discrepancies between physical stock and system records due to damages, 
breakages, count variances, or write-offs.

#### 3. Step-by-Step Workflows
- **How to Perform a Stock Adjustment:**
  1. Go to **Sidebar ➔ Inventory ➔ Operations ➔ Adjustments**.
  2. Click **'New Adjustment'**.
  3. Select the `Warehouse *` and `Adjustment Date *`.
  4. Choose `Adjustment Reason *` (`Damaged Goods`, `Cycle Count Variance`, `Found Stock`, `Expired Item`).
  5. Add items: select item, view current system balance, enter new physical quantity.
  6. Review net variance (`Difference Qty` and monetary valuation impact).
  7. Click **'Submit for Approval'** or **'Post Adjustment'**.
  8. Once posted, the stock ledger is updated immediately.

#### 4. Backend Validations & Rules
- **Negative Adjustment Limit:** An adjustment cannot reduce an item's quantity below zero unless `negative_stock_allowed` is enabled.
- **Lock After Posting:** Once an adjustment document is status `POSTED`, it is permanently locked and cannot be edited or deleted. Any corrections require an offsetting adjustment document.

---

### Feature: INTER-WAREHOUSE TRANSFERS

#### 1. Global navigation and entry flow
- **Route:** `/inventory/transfers`
- **Menu label:** Transfers
- **Menu key:** `inventory__transfers`
- **Default Group:** Operations
- **Required Permission:** `inventory_transfer.view`
- **Access Flow:** Sidebar ➔ Inventory ➔ Operations ➔ Transfers.

#### 2. Overview
Manages the physical relocation of stock from one warehouse (Source) to another (Destination). Supports 
direct one-step transfer and multi-step transfer with in-transit tracking.

#### 3. Step-by-Step Workflows
- **How to Transfer Stock Between Warehouses:**
  1. Go to **Sidebar ➔ Inventory ➔ Operations ➔ Transfers**.
  2. Click **'New Transfer'**.
  3. Select `Source Warehouse *` and `Destination Warehouse *` (must be different).
  4. Add items and specify the transfer quantity. Ensure `Transfer Qty <= Available Qty` in the Source Warehouse.
  5. If batch or serial tracked, allocate the specific batches/serials to be moved.
  6. Click **'Dispatch Transfer'**. The items move into `In-Transit` status.
  7. Upon arrival at the destination warehouse, the receiving officer opens the transfer record and clicks **'Confirm Receipt'**.
  8. Stock is added to the destination warehouse and removed from in-transit.

<a name="module-procurement"></a>
## Module: PROCUREMENT


The Procurement module automates vendor purchasing, purchase orders, goods receipt notes (GRN), 
supplier invoicing (3-way matching), and purchase returns.

### Feature: PURCHASE ORDERS (PO)

#### 1. Global navigation and entry flow
- **Route:** `/procurement/orders`
- **Menu label:** Purchase Orders
- **Menu key:** `procurement__orders`
- **Default Group:** Orders
- **Required Permission:** `procurement_order.view`
- **Access Flow:** Sidebar ➔ Procurement ➔ Orders ➔ Purchase Orders.

#### 2. Overview
Creates and manages legally binding purchase agreements sent to vendors for raw materials or finished products.

#### 3. Page layout and visible elements
- **Heading:** `Purchase Orders`
- **Action Buttons:** `+ New Purchase Order` (primary).
- **Status Filter Tabs:** `All`, `Draft`, `Sent / Confirmed`, `Partially Received`, `Received`, `Closed`, `Cancelled`.
- **Table Columns:**
  1. **PO Number:** Generated sequence (e.g. `PO-2026-0012`).
  2. **Supplier:** Vendor company name.
  3. **Order Date:** Creation date.
  4. **Expected Delivery:** Target receipt date.
  5. **Total Amount:** Currency formatted order total.
  6. **Receiving Status:** `Pending`, `Partial`, `Fully Received`.
  7. **Status Pill:** Current lifecycle stage.
  8. **Actions:** View Details, Edit (draft only), Send Email, Convert to GRN, Cancel PO.

#### 4. Step-by-Step Workflows
- **How to Create a Purchase Order:**
  1. Go to **Sidebar ➔ Procurement ➔ Orders ➔ Purchase Orders**.
  2. Click **'+ New Purchase Order'**.
  3. Select `Supplier *` from the registered vendor list.
  4. Specify `Delivery Warehouse *`, `Order Date`, and `Payment Terms`.
  5. Add items to the order table:
     - Select Item / SKU.
     - Enter `Quantity *` and agreed `Unit Price *`.
     - Select applicable Tax Rate (e.g., VAT 15%).
  6. Click **'Save as Draft'** or **'Approve & Send to Supplier'**.

---

### Feature: GOODS RECEIPT NOTES (GRN)

#### 1. Global navigation and entry flow
- **Route:** `/procurement/grns`
- **Menu label:** Goods Receipt
- **Menu key:** `procurement__grn`
- **Default Group:** Receiving
- **Required Permission:** `procurement_grn.view`
- **Access Flow:** Sidebar ➔ Procurement ➔ Receiving ➔ Goods Receipt.

#### 2. Overview
Logs the physical arrival and inspection of purchased goods at the warehouse dock. Automatically increases 
warehouse inventory balance and captures batch numbers, manufacturing dates, and serial codes.

#### 3. Step-by-Step Workflows
- **How to Receive Goods Against a PO:**
  1. Go to **Sidebar ➔ Procurement ➔ Receiving ➔ Goods Receipt**.
  2. Click **'New Goods Receipt'** (or click 'Receive' directly on an approved PO).
  3. Select the target Purchase Order number.
  4. System pre-populates ordered items and outstanding quantities.
  5. Enter `Received Quantity` for each line.
  6. If item is batch-tracked, enter `Batch Number *` and `Expiry Date *`. If serial-tracked, enter or scan serial numbers.
  7. Specify any rejected or damaged items with reason codes.
  8. Click **'Complete Receipt'**.
  9. Stock is immediately added to the warehouse stock balance and logged in the Stock Movement Ledger.

---

### Feature: SUPPLIER INVOICES (ACCOUNTS PAYABLE)

#### 1. Global navigation and entry flow
- **Route:** `/procurement/invoices`
- **Menu label:** Supplier Invoices
- **Menu key:** `procurement__invoices`
- **Default Group:** Post-Purchase
- **Required Permission:** `procurement_invoice.view`
- **Access Flow:** Sidebar ➔ Procurement ➔ Post-Purchase ➔ Supplier Invoices.

#### 2. Overview
Enforces 3-way matching between Purchase Order, Goods Receipt Note (GRN), and the vendor's billing invoice. 
Prevents paying for unreceived goods or pricing discrepancies.

<a name="module-finance"></a>
## Module: FINANCE & ACCOUNTING


The Finance module provides double-entry bookkeeping, Chart of Accounts (COA), Journal Entries, 
Fiscal Year management, Accounts Receivable (AR), Accounts Payable (AP), Bank Reconciliation, 
Cheque Management, and comprehensive financial statements (Trial Balance, P&L, Balance Sheet).

### Feature: CHART OF ACCOUNTS (COA)

#### 1. Global navigation and entry flow
- **Route:** `/finance/chart-of-accounts`
- **Menu label:** Chart of Accounts
- **Menu key:** `finance__chart_of_accounts`
- **Default Group:** Accounting
- **Required Permission:** `finance_account.view`
- **Access Flow:** Sidebar ➔ Finance ➔ Accounting ➔ Chart of Accounts.

#### 2. Overview
The foundational financial ledger structuring all accounts across five primary account types:
1. **Assets** (Code 1000s) - Cash, Bank, Accounts Receivable, Inventory, Fixed Assets.
2. **Liabilities** (Code 2000s) - Accounts Payable, Short-Term Loans, Accruals.
3. **Equity** (Code 3000s) - Share Capital, Retained Earnings, Owner Draw.
4. **Revenue** (Code 4000s) - Sales Income, Service Revenue, Discounts Received.
5. **Expenses** (Code 5000s) - Cost of Goods Sold (COGS), Salaries, Rent, Utilities, Depreciation.

#### 3. Step-by-Step Workflows
- **How to Create a New General Ledger Account:**
  1. Open **Sidebar ➔ Finance ➔ Accounting ➔ Chart of Accounts**.
  2. Click **'+ Add Account'**.
  3. Select `Account Type *` (Asset, Liability, Equity, Revenue, Expense).
  4. Enter `Account Code *` (e.g. `1210`) and `Account Name *` (e.g. `Commercial Bank Savings`).
  5. Select `Parent Account` if creating a sub-account.
  6. Specify `Currency` (default platform base currency).
  7. Click **'Save Account'**.

---

### Feature: JOURNAL ENTRIES

#### 1. Global navigation and entry flow
- **Route:** `/finance/journal-entries`
- **Menu label:** Journal Entries
- **Menu key:** `finance__journal_entries`
- **Default Group:** Accounting
- **Required Permission:** `finance_journal.view`
- **Access Flow:** Sidebar ➔ Finance ➔ Accounting ➔ Journal Entries.

#### 2. Overview
Manual and automated general journal postings. Enforces strict double-entry balancing: `Total Debits == Total Credits`.

#### 3. Backend Validations & Rules
- **Double-Entry Balance Constraint:** The system strictly rejects any journal entry where `SUM(debits) != SUM(credits)`.
- **Closed Period Lock:** Entries cannot be posted to a fiscal period marked as `LOCKED` or `CLOSED`.

---

### Feature: BANK ACCOUNTS & RECONCILIATION

#### 1. Global navigation and entry flow
- **Route:** `/finance/bank-accounts` and `/finance/bank-statements`
- **Menu labels:** Bank Accounts, Bank Statements
- **Menu keys:** `finance__bank_accounts`, `finance__bank_statements`
- **Default Group:** Banking
- **Required Permission:** `finance_bank.view`
- **Access Flow:** Sidebar ➔ Finance ➔ Banking ➔ Bank Accounts.

#### 2. Overview
Manages corporate bank accounts, upload of bank electronic statements (CSV/OFX), automated reconciliation 
matching bank ledger lines with ERP payments, and logging of bank service fees.

---

### Feature: CHEQUE REGISTRY & CHEQUE BOOKS

#### 1. Global navigation and entry flow
- **Route:** `/finance/cheque-registry` and `/finance/cheque-books`
- **Menu labels:** Cheque Registry, Cheque Books
- **Menu keys:** `finance__cheque_registry`, `finance__cheque_books`
- **Default Group:** Banking
- **Access Flow:** Sidebar ➔ Finance ➔ Banking ➔ Cheque Registry.

#### 2. Overview
Tracks the complete lifecycle of incoming and outgoing cheques:
- `In Hand`: Cheque received from customer, pending deposit.
- `Deposited`: Submitted to the bank for clearing.
- `Cleared`: Bank verified and funds realized.
- `Bounced / Returned`: Cheque dishonored by the bank; reverses receipt and reopens customer invoice.
- `Cancelled / Void`: Spoiled leaf or cancelled transaction.

<a name="module-hr"></a>
## Module: HUMAN RESOURCES & PAYROLL


The HR module handles employee records, organizational rosters, biometric attendance tracking, shift schedules, 
overtime policies, salary advances, and automated monthly payroll generation with statutory tax calculations.

### Feature: EMPLOYEES DIRECTORY

#### 1. Global navigation and entry flow
- **Route:** `/hr/employees`
- **Menu label:** Employees
- **Menu key:** `hr__employees`
- **Default Group:** Core
- **Required Permission:** `hr_employee.view`
- **Access Flow:** Sidebar ➔ HR ➔ Core ➔ Employees.

#### 2. Overview
Central directory of all full-time, part-time, and contracted personnel. Manages personal data, 
employment contracts, designation, department, basic remuneration, and bank disbursement accounts.

#### 3. Table Columns
1. **Employee ID:** Company employee code (e.g. `EMP-0145`).
2. **Name:** Full legal name and photo.
3. **Department:** Assigned business unit.
4. **Designation:** Job title.
5. **Employment Type:** Permanent, Probationary, Contract, Intern.
6. **Join Date:** Employment start date.
7. **Status:** Active, On Leave, Resigned, Terminated.

---

### Feature: ATTENDANCE & SHIFT ROSTER

#### 1. Global navigation and entry flow
- **Route:** `/hr/attendance` and `/hr/rosters`
- **Menu labels:** Daily Attendance, Roster Builder
- **Menu keys:** `hr__attendance`, `hr__rosters`
- **Default Group:** Attendance
- **Access Flow:** Sidebar ➔ HR ➔ Attendance ➔ Daily Attendance.

#### 2. Overview
Tracks daily clock-ins, biometric device imports, late arrivals, half-days, and shift schedules. 
Employees can submit attendance regularisation requests for supervisor approval if clock-in was missed.

---

### Feature: PAYROLL RUNS & PAYSLIPS

#### 1. Global navigation and entry flow
- **Route:** `/hr/payroll` and `/hr/payslips`
- **Menu labels:** Payroll, Payslips
- **Menu keys:** `hr__payroll`, `hr__payslips`
- **Default Group:** Payroll
- **Required Permission:** `hr_payroll.view`
- **Access Flow:** Sidebar ➔ HR ➔ Payroll ➔ Payroll.

#### 2. Overview
Executes monthly or bi-weekly salary calculation batches across the organization.

#### 3. Step-by-Step Workflows
- **How to Execute Monthly Payroll:**
  1. Open **Sidebar ➔ HR ➔ Payroll ➔ Payroll**.
  2. Click **'New Payroll Run'**.
  3. Select `Pay Period Month & Year *` and `Cutoff Cycle Date Range` (`start_date` to `end_date`).
  4. Select Department or "All Active Employees".
  5. Click **'Calculate Salaries'**:
     - System calculates Base Salary according to assigned Salary Structure.
     - Adds approved Overtime hours calculated via `OT Policies`.
     - Adds active monthly fixed allowances.
     - Deducts approved `Salary Advances` scheduled for this period.
     - Computes statutory withholdings (EPF, ETF, income taxes).
  6. Review the summary: Total Gross Pay, Total Deductions, Total Net Pay.
  7. Click **'Approve Payroll Run'**.
  8. Click **'Generate Payslips'** to distribute PDF payslips to employees.

<a name="module-jewelry"></a>
## Module: JEWELRY VERTICAL


Specialized enterprise suite engineered specifically for precious metal manufacturing, wholesale, 
and retail jewelry showrooms. Covers metal karat purities, live metal board rates, making charges, 
scrap gold trade-in, bespoke manufacturing job orders (Karigars), metal loss/wastage settlements, 
and stone/gemstone tracking.

### Feature: METAL BOARD RATES

#### 1. Global navigation and entry flow
- **Route:** `/jewelry/metal-rates`
- **Menu label:** Metal Rates
- **Menu key:** `jewelry__metal_rates`
- **Default Group:** Master Data
- **Access Flow:** Sidebar ➔ Jewelry ➔ Master Data ➔ Metal Rates.

#### 2. Overview
Defines real-time buying and selling market rates per gram for Gold (24K, 22K, 18K, 14K, 916 Hallmark), 
Silver, and Platinum. All showroom POS and wholesale price calculations dynamically reference these board rates.

---

### Feature: JEWELRY SHOWROOM POS & BILLING

#### 1. Global navigation and entry flow
- **Route:** `/jewelry/pos`
- **Menu label:** Point of Sale
- **Menu key:** `jewelry__pos`
- **Default Group:** Showroom
- **Access Flow:** Sidebar ➔ Jewelry ➔ Showroom ➔ Point of Sale.

#### 2. Overview
High-speed showroom counter billing terminal supporting:
- Barcode item scanning with precision weighing scale integration.
- Itemized breakdown: Gross Weight (g), Stone Weight (ct/g), Net Metal Weight (g).
- Dynamic metal pricing: `Net Weight * Daily Board Rate for Karat`.
- Making Charges: Calculated per gram, as a percentage of metal value, or flat rate.
- Old Gold Exchange / Scrap Payout: Trade in customer gold at tested purity to deduct directly from invoice total.
- Payment splitting across Cash, Credit Cards, and Gold Vouchers.

---

### Feature: KARIGAR (GOLDSMITH) JOB ORDERS & METAL RECONCILIATION

#### 1. Global navigation and entry flow
- **Route:** `/jewelry/karigar-orders` and `/jewelry/metal-issues`
- **Menu labels:** Karigar Orders, Metal Issues
- **Menu keys:** `jewelry__karigar_orders`, `jewelry__metal_issues`
- **Default Group:** Manufacturing
- **Access Flow:** Sidebar ➔ Jewelry ➔ Manufacturing ➔ Karigar Orders.

#### 2. Overview
Tracks precious metal issued to craftsmen (Karigars) for custom manufacturing and calculates allowable wastage:
- **Metal Issue:** Issues fine 24K gold bullion or pure silver alloy with recorded weight down to 0.001 grams.
- **Finished Item Return:** Craftsman returns finished jewelry item. System records gross weight and tested karat.
- **Scrap & Dust Return:** Unused metal and filing dust returned by craftsman.
- **Wastage Reconciliation:** Net metal consumed compared against the agreed contract wastage percentage. Discrepancies are billed or debited to the Karigar's pure metal balance account.

<a name="module-construction"></a>
## Module: CONSTRUCTION & PROJECTS


Engineered for general contractors, civil engineering, and infrastructure project management. 
Covers Work Breakdown Structures (WBS), Bill of Quantities (BOQ), Unit Cost Rate Cards, Project Budgets, 
Site Workforce Attendance, Quality Inspections, Safety Logs, Change Orders (Variations), and Daily Progress Reports.

### Feature: BILL OF QUANTITIES (BOQ) & RATE CARDS

#### 1. Global navigation and entry flow
- **Route:** `/construction/boq` and `/construction/rate-cards`
- **Menu labels:** BOQ, Rate Cards
- **Menu keys:** `construction__boq`, `construction__rate_cards`
- **Default Group:** Estimation & BOQ
- **Access Flow:** Sidebar ➔ Construction ➔ Estimation & BOQ ➔ BOQ.

#### 2. Overview
Defines line items of work, units of measurement, estimated quantities, and assembly unit rates (analyzing labor, 
materials, and plant/equipment costs per unit of work) to track progress billing against contractual milestones.

---

### Feature: VARIATIONS & CHANGE ORDERS

#### 1. Global navigation and entry flow
- **Route:** `/construction/variations`
- **Menu label:** Variations
- **Menu key:** `construction__variations`
- **Default Group:** Project Controls
- **Access Flow:** Sidebar ➔ Construction ➔ Project Controls ➔ Variations.

#### 2. Overview
Formalizes client requests for scope changes, additions, or omissions. Calculates cost impact, schedule extension 
days, and client sign-off before committing revisions to project budget and contracts.

<a name="module-money-exchange"></a>
## Module: MONEY EXCHANGE & REMITTANCES


Comprehensive suite for foreign currency exchange bureaus and remittance operators. 
Handles real-time exchange rates (Buy/Sell/Margin), Counter Exchange POS, Cashier Till reconciliation, 
Vault balances, Cross-Currency arbitrage, Wholesale bank trades, and Outward/Inward Remittances.

### Feature: RATES MANAGEMENT & COUNTER POS

#### 1. Global navigation and entry flow
- **Route:** `/money-exchange/rates` and `/money-exchange/pos`
- **Menu labels:** Rates Management, Point of Sale
- **Menu keys:** `money_exchange__rates`, `money_exchange__pos`
- **Default Group:** Operations
- **Access Flow:** Sidebar ➔ Money Exchange ➔ Operations ➔ Point of Sale.

#### 2. Overview
Allows counter tellers to perform instant currency conversion with anti-money laundering (AML) customer identification, 
automatic calculation of exchange margins, and tracking of physical cash drawer currency balances.

<a name="module-crm"></a>
## Module: CUSTOMER RELATIONSHIP MANAGEMENT (CRM)


Covers client interaction pipelines, deals, sales activities, customer inquiries, clarification threads, 
and cash inflow projections.

### Feature: DEAL SPACES & PIPELINES

#### 1. Global navigation and entry flow
- **Route:** `/crm/spaces`
- **Menu label:** Spaces
- **Menu key:** `crm__spaces`
- **Default Group:** Sales
- **Access Flow:** Sidebar ➔ CRM ➔ Sales ➔ Spaces.

#### 2. Overview
Visual Kanban board displaying deals progressing across customizable pipeline stages: 
`Lead Qualified` ➔ `Requirement Analysis` ➔ `Proposal Submitted` ➔ `Negotiation` ➔ `Closed Won` / `Closed Lost`.

<a name="module-production"></a>
## Module: PRODUCTION & MANUFACTURING


Manages multi-level Bills of Materials (BOM) and Phantom BOMs for manufacturing assembly and component consumption.

### Feature: BILLS OF MATERIALS (BOM)

#### 1. Global navigation and entry flow
- **Route:** `/production-min/boms`
- **Menu label:** Phantom BOMs
- **Menu key:** `production_min__phantom_boms`
- **Default Group:** Operations
- **Access Flow:** Sidebar ➔ Production ➔ Operations ➔ Phantom BOMs.

#### 2. Overview
Structures the recipe for manufactured items: lists raw materials, component quantities, scrap tolerances, 
and labor routing required to produce one finished product unit.

<a name="module-reporting"></a>
## Module: REPORTING & BUSINESS INTELLIGENCE


Universal reporting engine and analytics portal.

### Feature: REPORT CATALOG & REPORT BUILDER

#### 1. Global navigation and entry flow
- **Route:** `/reports` and `/reports/admin/reports`
- **Menu labels:** All Reports, Report Builder
- **Menu keys:** `reports__all`, `reports__builder`
- **Default Group:** General
- **Access Flow:** Sidebar ➔ Reports ➔ General ➔ All Reports.

#### 2. Overview
Access pre-built operational reports across Sales, Inventory, Finance, and Construction, or build custom tabular 
and graphical queries selecting metrics, dimensions, filters, and export schedules (PDF, Excel, CSV).

<a name="module-ai-analytics"></a>
## Module: AI ANALYTICS & INTELLIGENCE


Dedicated machine learning and predictive analytics engine.

### Feature: PREDICTIVE DEMAND FORECASTING & PRICING INTEL

#### 1. Global navigation and entry flow
- **Route:** `/ai-analytics/forecasting` and `/ai-analytics/pricing-intel`
- **Menu labels:** Forecasting, Pricing Intel
- **Menu keys:** `ai_analytics__forecasting`, `ai_analytics__pricing_intel`
- **Default Group:** Advanced Models
- **Access Flow:** Sidebar ➔ AI Analytics ➔ Advanced Models ➔ Forecasting.

#### 2. Overview
Utilizes historical transaction trends, seasonality, and lead times to project future stock requirements, 
prevent stockouts, and recommend optimal price elasticity points.

<a name="module-core"></a>
## Module: CORE SYSTEM ADMINISTRATION


The central host engine providing multi-tenancy isolation, organization hierarchy, user access management, 
Role-Based Access Control (RBAC), multi-currency configuration, terminal binding, custom field configurations, 
and multi-tier approval workflows.

### Feature: USERS & ROLE-BASED ACCESS CONTROL (RBAC)

#### 1. Global navigation and entry flow
- **Route:** `/users` and `/roles`
- **Menu labels:** Users, Roles
- **Menu keys:** `core__users`, `core__roles`
- **Default Group:** User Management
- **Required Permission:** `user.view`, `role.view`
- **Access Flow:** Sidebar ➔ Core ➔ User Management ➔ Users.

#### 2. Overview
- **Users:** Creation of staff logins, multi-factor authentication (MFA), password policies, and organization assignments.
- **Roles:** Fine-grained permission matrices granting or denying `create`, `view`, `update`, `delete`, `export`, and `approve` access to each individual module and entity across the ERP.

---

### Feature: MULTI-ORGANIZATION & MULTI-BRANCH

#### 1. Global navigation and entry flow
- **Route:** `/organizations`
- **Menu label:** Organizations
- **Menu key:** `core__organizations`
- **Default Group:** User Management
- **Required Permission:** `organization.view`
- **Access Flow:** Sidebar ➔ Core ➔ User Management ➔ Organizations.

#### 2. Overview
Structures parent corporations, holding companies, operating subsidiaries, and physical retail branches under a unified 
tenant database, with automated financial consolidation and inter-branch transactions.

---

### Feature: ITEM MASTER STOCK THRESHOLDS — MIN QTY (MASTER MINIMUM) & MAX QTY (MASTER MAXIMUM)

#### 1. Global navigation and entry flow
- **Route:** `/inventory/items` and `/inventory/stock-overview`
- **Menu labels:** Items, Stock Overview
- **Access Flow:** Sidebar ➔ Inventory ➔ Catalog ➔ Items (to configure per-item thresholds) and Sidebar ➔ Inventory ➔ Stock Management ➔ Stock Overview (to monitor threshold alerts).

#### 2. Item Master Minimum (`Min Qty` / `min_stock_level`) and Item Master Maximum (`Max Qty` / `max_stock_level`)
Yes — Apptimate One provides both an **Item Master Minimum (`Min Qty`)** and an **Item Master Maximum (`Max Qty`)** setting on every catalog item under **Sidebar ➔ Inventory ➔ Catalog ➔ Items** (stored in `inventory_item_replenishment_rules.min_stock_level` and `inventory_item_replenishment_rules.max_stock_level`), alongside **Reorder Level (`reorder_point`)** and **Reorder Qty (`reorder_qty`)**:
- **Min Qty (`min_stock_level` — Master Minimum):** Optional numeric stock threshold (`>= 0`). In **Stock Overview** (**Sidebar ➔ Inventory ➔ Stock Management ➔ Stock Overview**), when an item's positive available stock is below its configured `Min Qty` (`min_stock_level`), it is flagged with status **Critical** (and `0` available stock is flagged **Out of Stock**).
- **Max Qty (`max_stock_level` — Master Maximum):** Optional numeric stock threshold (`>= 0`). In **Stock Overview**, when an item's positive available stock exceeds its configured positive `Max Qty` (`max_stock_level`), it is flagged with status **Overstock**.
- **Reorder Level (`reorder_point`) & Reorder Qty (`reorder_qty`):** Optional replenishment thresholds used to trigger low-stock reorder alerts when available stock is at or below `reorder_point`.
- **Important distinction from Sales/Purchase transaction limits:** Both **Min Qty (`min_stock_level`)** and **Max Qty (`max_stock_level`)** are inventory stock-monitoring thresholds on the Item Master — they do **not** act as automatic per-transaction quantity caps on customer POS/Sales Order lines or supplier Purchase Order lines.
