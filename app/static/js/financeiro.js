document.addEventListener("DOMContentLoaded", function() {
    // 1. Data Automática
    const dateInput = document.querySelector('input[name="data"]');
    if (dateInput && !dateInput.value) {
        const today = new Date();
        dateInput.value = today.toISOString().split('T')[0];
    }

    // --- LÓGICA DE FEEDBACK (LOADER) ---
    const loader = document.getElementById('loader-overlay');
    const msg = document.getElementById('loader-msg');

    function showLoader(texto) {
        msg.innerText = texto;
        loader.style.display = 'flex';
    }

    // A. Feedback ao trocar Cliente no Dropdown
    const formBusca = document.getElementById('form-busca');
    const selectCliente = document.querySelector('.search-select');
    
    if (selectCliente && formBusca) {
        selectCliente.addEventListener('change', function() {
            // Verifica se realmente selecionou alguém (não vazio)
            if (this.value) {
                showLoader('🔄 Buscando ficha do cliente...\nIsso pode levar alguns segundos.');
                // O form será submetido automaticamente pelo onchange="submit()" no HTML
                // mas o loader já estará na tela
            }
        });
    }

    // B. Feedback ao Confirmar Pagamento
    const formPagamento = document.getElementById('form-pagamento');
    if (formPagamento) {
        formPagamento.addEventListener('submit', function() {
            showLoader('💰 Registrando pagamento e recalculando saldo...\nPor favor, aguarde.');
        });
    }

    // C. Feedback ao Excluir (Lógica Blindada)
    // Seleciona pela classe que acabamos de criar no HTML
    const deleteForms = document.querySelectorAll('.form-excluir');
    
    deleteForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            // 1. Impede o envio imediato
            e.preventDefault(); 
            
            // 2. Pergunta ao usuário
            if (confirm('Tem certeza que deseja excluir este pagamento?')) {
                // 3. Se disse SIM: Mostra o loader
                showLoader('🗑️ Excluindo pagamento e atualizando extrato...');
                
                // 4. Envia o formulário manualmente após mostrar a mensagem
                this.submit();
            }
            // Se disse NÃO, nada acontece (o preventDefault já parou tudo)
        });
    });

    // D. Segurança para iOS (Safari)
    // Se o usuário clicar em "Voltar" no navegador, o loader pode ficar travado.
    // Isso força esconder o loader sempre que a página é carregada/restaurada.
    window.addEventListener('pageshow', function() {
        loader.style.display = 'none';
    });
});

// Funções de UI (Abas e Toggle)
function toggleExtrato() {
    const el = document.getElementById('areaExtrato');
    const btn = document.getElementById('btnExtrato');
    
    if (el.style.display === 'none' || el.style.display === '') {
        el.style.display = 'block';
        btn.innerHTML = '📂 Ocultar Extrato';
        setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    } else {
        el.style.display = 'none';
        btn.innerHTML = '📂 Ver Extrato / Conferência';
    }
}

function switchTab(tabName) {
    document.getElementById('content-pedidos').style.display = 'none';
    document.getElementById('content-historico').style.display = 'none';
    document.getElementById('tab-pedidos').classList.remove('active');
    document.getElementById('tab-historico').classList.remove('active');

    document.getElementById('content-' + tabName).style.display = 'block';
    document.getElementById('tab-' + tabName).classList.add('active');
}