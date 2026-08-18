git add -A; if ($?) { git commit -m @'
Read the IVA aliquot from the line in type A invoices

Only A discriminates IVA per line, and its row layout differs from B and C:
it drops Imp. Bonif. and adds Alicuota IVA and Subtotal c/IVA. The item
pattern demanded exactly three trailing columns, so no line of an A invoice
matched at all -- the items were dropped in silence rather than the aliquot
merely being wrong. Deducing the rate from the letter is also wrong on its
own terms, since one A voucher can mix 21% and 10,5%.

The unit of measure was hardcoded to "unidades", which dropped any line
billed in horas or kilogramos the same silent way, in B and C too.

The receptor's address is labelled "Domicilio Comercial:" in A against
"Domicilio:" in B and C, so A invoices lost the customer's IVA condition
and address as well.

Only the two known column widths match. An unrecognised layout should drop
the line visibly, where needs_manual_items reports it, rather than match
shifted and put some other column's number in the tax field.

'@ }