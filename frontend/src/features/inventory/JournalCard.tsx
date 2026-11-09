import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { formatDate, formatIDR } from '@/lib/format';
import type { Journal } from './api';

/** The balanced journal a document posted (read-only). */
export function JournalCard({ journal }: { journal: Journal }) {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {t('ledger.journal')} {journal.number}
        </CardTitle>
        <p className="text-small text-fg-secondary">{formatDate(journal.entry_date)}</p>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>{t('ledger.account')}</TH>
              <TH className="text-right">{t('ledger.debit')}</TH>
              <TH className="text-right">{t('ledger.credit')}</TH>
            </TR>
          </THead>
          <TBody>
            {journal.lines.map((l, i) => (
              <TR key={i}>
                <TD>
                  {l.account_code} · {t(`ledger.accounts.${l.account_code}`, { defaultValue: '' })}
                  {l.cost_element_code && (
                    <span className="block text-caption text-fg-muted">{l.cost_element_code}</span>
                  )}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {Number(l.debit) ? formatIDR(l.debit) : ''}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {Number(l.credit) ? formatIDR(l.credit) : ''}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}
