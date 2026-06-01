import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Globe } from 'lucide-react';

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();

  const toggleLanguage = () => {
    const newLang = i18n.language === 'en' ? 'zh' : 'en';
    i18n.changeLanguage(newLang);
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggleLanguage}
      className="text-xs flex items-center gap-1"
    >
      <Globe className="w-3.5 h-3.5" />
      <span>{t('language.' + (i18n.language === 'en' ? 'zh' : 'en'))}</span>
    </Button>
  );
}