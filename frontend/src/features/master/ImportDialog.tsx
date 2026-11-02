import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError, downloadFile } from '@/lib/api';
import { useImport, type EntityMeta } from './api';

export function ImportDialog({ meta, onClose }: { meta: EntityMeta; onClose: () => void }) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const run = useImport(meta.key);
  const result = run.data;
  const label = (name: string | null) =>
    meta.fields.find((f) => f.name === name)?.label ?? name ?? '–';

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('master.importTitle', { entity: meta.label })}
      description={t('master.importHelp')}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button
            variant="primary"
            disabled={!file || run.isPending}
            onClick={() => file && run.mutate(file)}
          >
            <Icon name="upload" /> {t('master.importRun')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Button
          variant="secondary"
          className="self-start"
          onClick={() =>
            void downloadFile(`/master/${meta.key}/template`, `template-${meta.key}.csv`)
          }
        >
          <Icon name="download" /> {t('master.template')}
        </Button>
        <label className="flex flex-col gap-1.5 text-small font-semibold text-fg">
          {t('master.importFile')}
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              run.reset();
            }}
            className="text-small text-fg-body file:mr-3 file:rounded-control file:border file:border-border-strong file:bg-transparent file:px-3 file:py-1.5 file:font-semibold file:text-fg"
          />
        </label>
        <FormError message={run.error instanceof ApiError ? run.error.message : null} />
        {result?.ok && (
          <p
            role="status"
            className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
          >
            {t('master.importDone', { created: result.created, updated: result.updated })}
          </p>
        )}
        {result && !result.ok && (
          <>
            <FormError message={t('master.importFailed', { count: result.errors.length })} />
            <div className="max-h-64 overflow-auto rounded-card border border-border">
              <Table>
                <caption className="sr-only">{t('master.importErrors')}</caption>
                <THead>
                  <TR>
                    <TH numeric>{t('master.row')}</TH>
                    <TH>{t('master.column')}</TH>
                    <TH>{t('master.problem')}</TH>
                  </TR>
                </THead>
                <TBody>
                  {result.errors.map((e, i) => (
                    <TR key={i}>
                      <TD numeric>{e.row ?? '–'}</TD>
                      <TD>{label(e.field)}</TD>
                      <TD>{e.message}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}
