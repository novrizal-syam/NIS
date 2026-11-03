import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAuth } from '@/features/auth/AuthProvider';
import { FilterTile } from '@/features/crm/CrmPills';
import { downloadFile } from '@/lib/api';
import { formatIDR } from '@/lib/format';
import { PROJECT_STATUSES, projectExportPath, useProjects, type ProjectStatus } from './api';
import { ProjectStatusPill } from './ProjectStatusPill';

export function ProjectsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<ProjectStatus | ''>('');
  const [page, setPage] = useState(1);
  const list = useProjects({ q, status, page });
  const data = list.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {PROJECT_STATUSES.map((s) => (
          <FilterTile
            key={s}
            label={t(`project.status.${s}`)}
            value={data?.counts[s] ?? '–'}
            active={status === s}
            onClick={() => {
              setStatus(status === s ? '' : s);
              setPage(1);
            }}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('project.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        {can('project', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(projectExportPath({ q, status }), 'proyek.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('project.name')}</TH>
              <TH>{t('master.status')}</TH>
              <TH>{t('project.contract')}</TH>
              <TH className="text-right">{t('project.revenue')}</TH>
              <TH className="text-right">{t('project.budget')}</TH>
              <TH className="text-right">{t('project.plannedMargin')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-8 text-center text-fg-secondary">
                  {t('project.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((p) => (
              <TR key={p.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/proyek/${p.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {p.number}
                  </Link>
                </TD>
                <TD className="min-w-56">
                  {p.name}
                  <span className="block text-caption text-fg-muted">{p.company_name}</span>
                </TD>
                <TD>
                  <ProjectStatusPill status={p.status} />
                </TD>
                <TD>{p.contract_number ?? '–'}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(p.revenue)}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(p.budget_total)}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(p.planned_margin)}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
